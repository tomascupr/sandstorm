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
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests

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
    event_type = body.get("type", "")

    if event_type == "ADDED_TO_SPACE":
        return {
            "text": "Hi! I'm Sandstorm — I run general-purpose agent tasks in secure sandboxes. "
            "Mention me or DM me with a task!"
        }

    return {}


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
