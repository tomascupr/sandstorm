"""Slack events endpoint for FastAPI — mounts slack-bolt as an HTTP handler."""

from __future__ import annotations

import asyncio
import logging
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Slack"])

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
    if not os.environ.get("SLACK_BOT_TOKEN"):
        return JSONResponse({"error": "SLACK_BOT_TOKEN not configured"}, status_code=503)

    # Acknowledge retries immediately — Slack retries if we don't ack within 3s,
    # but agent runs take much longer. The primary event is already being processed.
    if request.headers.get("X-Slack-Retry-Num"):
        return JSONResponse({"ok": True})

    # Delegate to slack-bolt (handles signature verification, URL verification, events)
    handler = await _get_handler()
    return await handler.handle(request)
