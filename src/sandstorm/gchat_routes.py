"""Google Chat events endpoint for FastAPI."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Google Chat"])


def _verify_google_chat_jwt(auth_header: str) -> bool:
    """Verify the Bearer JWT from Google Chat."""
    if not auth_header.startswith("Bearer "):
        return False
    token = auth_header[7:]
    project_number = os.environ.get("GOOGLE_CHAT_PROJECT_NUMBER", "")
    if not project_number:
        logger.warning("GOOGLE_CHAT_PROJECT_NUMBER not set — cannot verify JWT")
        return False
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        claim = id_token.verify_token(
            token,
            google_requests.Request(),
            audience=project_number,
            certs_url="https://www.googleapis.com/service_accounts/v1/metadata/x509/chat@system.gserviceaccount.com",
        )
        return claim.get("iss") == "chat@system.gserviceaccount.com"
    except Exception:
        logger.warning("Google Chat JWT verification failed", exc_info=True)
        return False


async def _dispatch_event(body: dict) -> dict:
    """Route a Google Chat event to the appropriate handler."""
    from .gchat import dispatch_slash_command, parse_event_type

    event_type = parse_event_type(body)

    if event_type == "added_to_space":
        return {
            "text": "Hi! I'm Sandstorm — I run general-purpose agent tasks in secure sandboxes. "
            "Mention me or DM me with a task!"
        }

    if event_type == "slash_command":
        user_name = body.get("user", {}).get("name", "")
        space_name = body.get("space", {}).get("name", "")
        return dispatch_slash_command(body, team_id=space_name, user_id=user_name)

    if event_type == "app_home":
        from .gchat_app_home import build_home_card
        user_name = body.get("user", {}).get("name", "")
        space_name = body.get("space", {}).get("name", "")
        card = build_home_card(team_id=space_name, user_id=user_name)
        return {"cardsV2": [card]}

    if event_type == "card_clicked":
        return await _handle_card_clicked(body)

    if event_type == "reaction_added":
        return await _handle_reaction(body)

    # MESSAGE events (mention, dm_message) will be handled in a later task
    # when the full agent run pipeline is wired up.

    return {}


async def _handle_card_clicked(body: dict) -> dict:
    """Handle interactive card button clicks (e.g. feedback)."""
    action = body.get("action", {})
    method = action.get("actionMethodName", "")
    params = {p["key"]: p["value"] for p in action.get("parameters", [])}

    if method == "sandstorm_feedback":
        from .store import run_store

        run_id = params.get("run_id", "")
        sentiment = params.get("sentiment", "")
        user = body.get("user", {}).get("name", "")
        if run_id and sentiment:
            run_store.set_feedback(run_id, sentiment, user)
        emoji = "\U0001f44d" if sentiment == "positive" else "\U0001f44e"
        return {"text": f"{emoji} Feedback recorded. Thanks!"}

    if method == "sandstorm_cancel_run":
        from .cancellation import request_cancellation
        from .store import run_store

        run_id = params.get("run_id", "")
        user = body.get("user", {}).get("name", "")
        space = body.get("space", {}).get("name", "")
        if not run_id:
            return {"text": "No run to cancel."}
        run = run_store.get(run_id)
        if run is None or run.team_id != space or run.user_id != user:
            return {"text": "Run not found or not yours."}
        if run.status != "running":
            return {"text": f"Run `{run_id}` is already finished."}
        request_cancellation(run_id)
        return {"text": f"Cancelled run `{run_id}`."}

    if method == "sandstorm_forget_memory":
        from .memory import memory_store
        memory_id = params.get("memory_id", "")
        user = body.get("user", {}).get("name", "")
        space = body.get("space", {}).get("name", "")
        if memory_id:
            memory_store.forget_by_id(memory_id, team_id=space, user_id=user, scope="user")
        return {"text": "Memory forgotten."}

    return {}


async def _handle_reaction(body: dict) -> dict:
    """Handle REACTION_ADDED events — match against triggers."""
    from .config import load_sandstorm_config
    from .gchat import unicode_to_shortcode
    from .triggers import load_triggers

    emoji_unicode = body.get("reaction", {}).get("unicode", "")
    shortcode = unicode_to_shortcode(emoji_unicode)
    if not shortcode:
        return {}

    space_name = body.get("space", {}).get("name", "")

    config = load_sandstorm_config()
    if config is None:
        return {}
    try:
        triggers = load_triggers(config)
    except ValueError:
        return {}

    matches = [
        t
        for t in triggers
        if t.type == "reaction"
        and t.emoji == shortcode
        and (not t.channels or space_name in t.channels)
    ]
    if not matches:
        return {}

    # Reaction triggers will fire agent runs in a future task
    # For now, acknowledge the trigger match
    return {"text": f"Trigger matched: {matches[0].name}"}


@router.post("/gchat/events")
async def gchat_events(request: Request):
    """Handle all Google Chat events."""
    if not os.environ.get("GOOGLE_CHAT_SERVICE_ACCOUNT_KEY"):
        return JSONResponse({"error": "Google Chat not configured"}, status_code=503)

    auth_header = request.headers.get("Authorization", "")
    if not _verify_google_chat_jwt(auth_header):
        return JSONResponse({"error": "invalid token"}, status_code=401)

    body = await request.json()
    result = await _dispatch_event(body)
    return JSONResponse(result)
