"""Slack events endpoint for FastAPI — mounts slack-bolt as an HTTP handler."""

from __future__ import annotations

import asyncio
import logging
import os
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Slack"])

# Dedup cache: event_id -> timestamp
_seen_events: dict[str, float] = {}
_DEDUP_TTL = 60  # seconds

# Lazy singleton with async lock to prevent duplicate initialization
_handler = None
_handler_lock = asyncio.Lock()


async def _get_handler():
    """Lazily create the slack-bolt handler (imports slack deps on first call)."""
    global _handler
    if _handler is not None:
        return _handler

    async with _handler_lock:
        if _handler is not None:
            return _handler

        from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler

        from .slack import create_slack_app

        slack_app = create_slack_app(process_before_response=True)
        _handler = AsyncSlackRequestHandler(slack_app)
        return _handler


@router.post("/slack/events")
async def slack_events(request: Request):
    """Handle Slack event subscriptions (URL verification, events, interactions)."""
    # Gate on token presence
    if not os.environ.get("SLACK_BOT_TOKEN"):
        return JSONResponse({"error": "SLACK_BOT_TOKEN not configured"}, status_code=503)

    # Reject retries (Slack sends these if we don't ack within 3s)
    if request.headers.get("X-Slack-Retry-Num"):
        return JSONResponse({"ok": True})

    # URL verification challenge (Slack sends this when configuring the Request URL)
    body = await request.json()
    if body.get("type") == "url_verification":
        return JSONResponse({"challenge": body["challenge"]})

    # Deduplicate events
    event_id = body.get("event_id")
    if event_id:
        now = time.time()
        # Prune stale entries
        stale = [k for k, v in _seen_events.items() if now - v > _DEDUP_TTL]
        for k in stale:
            del _seen_events[k]
        if event_id in _seen_events:
            return JSONResponse({"ok": True, "duplicate": True})
        _seen_events[event_id] = now

    # Delegate to slack-bolt
    handler = await _get_handler()
    return await handler.handle(request)
