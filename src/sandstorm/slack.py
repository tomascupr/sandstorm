"""Slack bot integration for Sandstorm — run agents via @mentions and DMs."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import time
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING

from .models import QueryRequest
from .sandbox import run_agent_in_sandbox
from .store import run_store

if TYPE_CHECKING:
    from slack_bolt.async_app import AsyncApp

logger = logging.getLogger(__name__)

# Max file size to download from Slack threads (10 MB)
_MAX_FILE_SIZE = 10 * 1024 * 1024

# Max sandbox pool entries (one per active thread)
_MAX_SANDBOX_POOL = 1000

# MIME prefixes treated as binary (downloaded as bytes, not text)
_BINARY_MIME_PREFIXES = ("image/", "audio/", "video/", "application/pdf", "application/zip")


# ── Metadata blocks ──────────────────────────────────────────────────────────


def _build_metadata_blocks(
    run_id: str,
    model: str | None,
    cost_usd: float | None,
    num_turns: int | None,
    duration_secs: float | None,
) -> list[dict]:
    """Block Kit footer: context line (model|turns|cost|duration) + feedback buttons."""
    parts = []
    if model:
        parts.append(f"Model: {model}")
    if num_turns is not None:
        parts.append(f"Turns: {num_turns}")
    if cost_usd is not None:
        parts.append(f"Cost: ${cost_usd:.4f}")
    if duration_secs is not None:
        parts.append(f"Duration: {duration_secs:.1f}s")

    blocks: list[dict] = []
    if parts:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": " | ".join(parts)}],
            }
        )
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "\U0001f44d Helpful"},
                    "action_id": "sandstorm_feedback_positive",
                    "value": run_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "\U0001f44e Not helpful"},
                    "action_id": "sandstorm_feedback_negative",
                    "value": run_id,
                },
            ],
        }
    )
    return blocks


# ── Query builder ─────────────────────────────────────────────────────────────


def _build_query_request(prompt: str, files: dict[str, str] | None = None) -> QueryRequest:
    """Build QueryRequest from prompt + env var defaults.

    Uses SANDSTORM_SLACK_MODEL, SANDSTORM_SLACK_TIMEOUT env vars.
    API keys resolved by QueryRequest.resolve_api_keys() as usual.
    """
    model = os.environ.get("SANDSTORM_SLACK_MODEL")
    timeout_str = os.environ.get("SANDSTORM_SLACK_TIMEOUT", "300")
    try:
        timeout = int(timeout_str)
    except ValueError:
        timeout = 300

    return QueryRequest(
        prompt=prompt,
        model=model,
        timeout=timeout,
        files=files,
        anthropic_api_key=None,
        e2b_api_key=None,
        openrouter_api_key=None,
        max_turns=None,
    )


# ── Thread helpers ────────────────────────────────────────────────────────────


async def _fetch_thread_messages(client, channel: str, thread_ts: str) -> list[dict]:
    """Fetch all messages in a thread via conversations_replies().

    Uses cursor-based pagination to handle threads with >200 messages.
    Returns the raw messages list, or [] on error.
    """
    try:
        messages: list[dict] = []
        cursor = None
        while True:
            kwargs: dict = {"channel": channel, "ts": thread_ts, "limit": 200}
            if cursor:
                kwargs["cursor"] = cursor
            result = await client.conversations_replies(**kwargs)
            messages.extend(result.get("messages", []))
            cursor = result.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
        return messages
    except Exception:
        logger.warning("Failed to fetch thread replies", exc_info=True)
        return []


def _gather_thread_context(messages: list[dict], bot_user_id: str) -> str:
    """Format thread messages into a context string.

    Includes bot's own messages (prefixed [Sandstorm]) for conversational
    continuity. Includes file names/types for user messages.
    Returns formatted string like:
      [Alice] Hey, this CSV has duplicate rows...
      [Alice] [attached: data.csv (text/csv, 15KB)]
      [Bob] @Sandstorm deduplicate this CSV...
      [Sandstorm] Here's my analysis of the data...
    """
    lines: list[str] = []
    for msg in messages:
        user = msg.get("user", "unknown")
        text = msg.get("text", "").strip()

        # Include bot's own messages for conversational continuity
        if user == bot_user_id:
            if text:
                lines.append(f"[Sandstorm] {text}")
            continue  # skip file attachments from bot

        if text:
            lines.append(f"[{user}] {text}")

        # Note attached files
        for f in msg.get("files", []):
            name = f.get("name", "unknown")
            mimetype = f.get("mimetype", "unknown")
            size = f.get("size", 0)
            size_kb = size / 1024
            lines.append(f"[{user}] [attached: {name} ({mimetype}, {size_kb:.0f}KB)]")

    return "\n".join(lines)


# ── File handling ─────────────────────────────────────────────────────────────


async def _download_thread_files(
    client, messages: list[dict], bot_user_id: str
) -> tuple[dict[str, str], dict[str, bytes]]:
    """Download files shared in the thread.

    Returns (text_files, binary_files):
      - text_files: {filename: str_content} for QueryRequest.files
      - binary_files: {filename: bytes_content} for sandbox upload
    Skips files > 10MB.
    """
    try:
        import aiohttp
    except ImportError:
        logger.warning("aiohttp not available for file downloads")
        return {}, {}

    text_files: dict[str, str] = {}
    binary_files: dict[str, bytes] = {}

    headers = {"Authorization": f"Bearer {client.token}"}
    async with aiohttp.ClientSession(headers=headers) as session:
        for msg in messages:
            if msg.get("user") == bot_user_id:
                continue

            for f in msg.get("files", []):
                name = f.get("name", "unknown")
                mimetype = f.get("mimetype", "")
                size = f.get("size", 0)
                is_binary = any(mimetype.startswith(prefix) for prefix in _BINARY_MIME_PREFIXES)

                # Skip large files
                if size > _MAX_FILE_SIZE:
                    logger.warning("Skipping large file: %s (%d bytes)", name, size)
                    continue

                url = f.get("url_private_download") or f.get("url_private")
                if not url:
                    continue

                # Text files: try files_info API first (returns content directly)
                if not is_binary:
                    try:
                        resp = await client.files_info(file=f["id"])
                        content_resp = resp.get("content")
                        if content_resp:
                            text_files[name] = content_resp
                            continue
                    except Exception:
                        pass

                # Download via URL with bot token auth
                try:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            if is_binary:
                                binary_files[name] = await resp.read()
                            else:
                                text_files[name] = await resp.text()
                        else:
                            logger.warning("Failed to download %s: HTTP %d", name, resp.status)
                except Exception:
                    logger.warning("Failed to download file: %s", name, exc_info=True)

    return text_files, binary_files


# ── Event mapping / streaming bridge ──────────────────────────────────────────


async def _stream_to_slack(
    request: QueryRequest,
    run_id: str,
    streamer,
    client,
    channel: str,
    thread_ts: str,
    set_status: Callable | None = None,
    *,
    keep_alive: bool = False,
    sandbox_id: str | None = None,
    sandbox_id_out: list[str] | None = None,
    binary_files: dict[str, bytes] | None = None,
) -> dict:
    """Core bridge: consume run_agent_in_sandbox() -> stream to Slack.

    Args:
        streamer: Chat stream object from client.chat_stream()
        set_status: Optional async callable (only in Assistant context).
        Returns metadata dict {model, cost_usd, num_turns, duration_secs, error}.
    """
    metadata: dict = {
        "model": None,
        "cost_usd": None,
        "num_turns": None,
        "duration_secs": None,
        "error": None,
    }

    start = time.monotonic()
    stopped = False

    run_store.create(
        id=run_id,
        prompt=request.prompt,
        model=request.model,
        files_count=len(request.files) if request.files else 0,
    )

    try:
        async for line in run_agent_in_sandbox(
            request,
            run_id,
            keep_alive=keep_alive,
            sandbox_id=sandbox_id,
            sandbox_id_out=sandbox_id_out,
            binary_files=binary_files,
        ):
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue

            event_type = event.get("type")
            logger.info("[%s] Event: %s", run_id, event_type)

            if event_type == "system" and event.get("subtype") == "init":
                model = event.get("model")
                metadata["model"] = model
                if set_status:
                    await set_status(f"Running agent on {model}...")

            elif event_type == "assistant":
                message = event.get("message", {})
                for block in message.get("content", []):
                    if block.get("type") == "text":
                        text = block["text"]
                        if text:
                            try:
                                await streamer.append(markdown_text=text)
                                logger.info("[%s] Streamed %d chars", run_id, len(text))
                            except Exception:
                                logger.error("[%s] streamer.append failed", run_id, exc_info=True)
                    elif block.get("type") == "tool_use":
                        tool_name = block.get("name", "unknown")
                        logger.info("[%s] Tool: %s", run_id, tool_name)
                        if set_status:
                            await set_status(f"Using {tool_name}...")

            elif event_type == "result":
                cost = event.get("total_cost_usd")
                metadata["cost_usd"] = cost if cost is not None else event.get("cost_usd")
                metadata["num_turns"] = event.get("num_turns")
                metadata["duration_secs"] = round(time.monotonic() - start, 1)
                metadata["model"] = event.get("model") or metadata["model"]
                logger.info(
                    "[%s] Result: turns=%s cost=%s",
                    run_id,
                    metadata["num_turns"],
                    metadata["cost_usd"],
                )

                footer_blocks = _build_metadata_blocks(
                    run_id,
                    metadata["model"],
                    metadata["cost_usd"],
                    metadata["num_turns"],
                    metadata["duration_secs"],
                )
                try:
                    await streamer.stop(blocks=footer_blocks)
                    stopped = True
                    logger.info("[%s] Stream stopped with footer", run_id)
                except Exception:
                    logger.error("[%s] streamer.stop failed", run_id, exc_info=True)

                run_store.complete(
                    run_id,
                    cost_usd=metadata["cost_usd"],
                    num_turns=metadata["num_turns"],
                    duration_secs=metadata["duration_secs"],
                    model=metadata["model"],
                )

            elif event_type == "error":
                error_msg = event.get("error", "Unknown error")
                metadata["error"] = error_msg
                metadata["duration_secs"] = round(time.monotonic() - start, 1)
                logger.error("[%s] Agent error: %s", run_id, error_msg)

                try:
                    await streamer.append(markdown_text=f"\n:warning: Error: {error_msg}")
                    await streamer.stop()
                    stopped = True
                except Exception:
                    logger.error("[%s] streamer.stop (error) failed", run_id, exc_info=True)

                run_store.fail(run_id, error_msg, metadata["duration_secs"])

            # Skip user, stderr, warning events (log server-side only)
            elif event_type in ("user", "stderr", "warning"):
                logger.debug("[%s] %s", run_id, event_type)

    except Exception as exc:
        metadata["error"] = str(exc)
        metadata["duration_secs"] = round(time.monotonic() - start, 1)
        logger.error("[%s] Stream error: %s", run_id, exc, exc_info=True)
        run_store.fail(run_id, str(exc), metadata["duration_secs"])
    finally:
        # Always stop the streamer to avoid dangling streams in Slack
        if not stopped:
            with contextlib.suppress(Exception):
                await streamer.stop()

    return metadata


# ── App factory ───────────────────────────────────────────────────────────────


def create_slack_app(
    *, bot_token: str | None = None, signing_secret: str | None = None
) -> AsyncApp:
    """Create and configure the Slack Bolt AsyncApp."""
    from slack_bolt.async_app import AsyncApp
    from slack_bolt.middleware.assistant.async_assistant import AsyncAssistant

    token = bot_token or os.environ.get("SLACK_BOT_TOKEN")
    app = AsyncApp(token=token, signing_secret=signing_secret)

    # Sandbox reuse pool: (channel, thread_ts) -> (sandbox_id, lock)
    # Lock serializes concurrent @mentions in the same thread
    _sandbox_pool: dict[tuple[str, str], tuple[str | None, asyncio.Lock]] = {}

    # ── 1. @mention handler — primary interaction in channels ──

    @app.event("app_mention")
    async def handle_mention(event, client, say, context):
        channel = event["channel"]
        thread_ts = event.get("thread_ts", event["ts"])
        user_id = event["user"]
        bot_user_id = context["bot_user_id"]

        # Extract prompt (strip @mention)
        raw_text = event.get("text", "")
        prompt = re.sub(r"<@[A-Z0-9]+>", "", raw_text).strip()
        if not prompt:
            await say(text="Mention me with a task!", thread_ts=thread_ts)
            return

        # Add :eyes: reaction as status indicator (set_status not available here)
        with contextlib.suppress(Exception):
            await client.reactions_add(channel=channel, timestamp=event["ts"], name="eyes")

        run_id = uuid.uuid4().hex[:8]
        messages = await _fetch_thread_messages(client, channel, thread_ts)
        thread_context = _gather_thread_context(messages, bot_user_id)
        text_files, binary_files = await _download_thread_files(client, messages, bot_user_id)

        full_prompt = prompt
        if thread_context:
            full_prompt = f"Thread context:\n{thread_context}\n\nUser request: {prompt}"

        all_files = list(text_files.keys()) + list(binary_files.keys())
        if all_files:
            file_list = "\n".join(f"- /home/user/{f}" for f in all_files)
            full_prompt += f"\n\nFiles available in your working directory:\n{file_list}"

        request = _build_query_request(full_prompt, text_files or None)

        # Get or create sandbox pool entry for this thread
        key = (channel, thread_ts)
        if key not in _sandbox_pool:
            _sandbox_pool[key] = (None, asyncio.Lock())
        _, lock = _sandbox_pool[key]

        async with lock:
            # Read sandbox_id inside lock to avoid TOCTOU race
            existing_sandbox_id = _sandbox_pool[key][0]
            sandbox_id_out: list[str] = []
            reuse_succeeded = False
            if existing_sandbox_id:
                logger.info(
                    "[%s] Reusing sandbox %s for thread %s",
                    run_id,
                    existing_sandbox_id,
                    thread_ts,
                )
                streamer = await client.chat_stream(
                    channel=channel,
                    thread_ts=thread_ts,
                    recipient_team_id=context.get("team_id"),
                    recipient_user_id=user_id,
                )
                metadata = await _stream_to_slack(
                    request,
                    run_id,
                    streamer,
                    client,
                    channel,
                    thread_ts,
                    keep_alive=True,
                    sandbox_id=existing_sandbox_id,
                    binary_files=binary_files or None,
                )
                reuse_succeeded = not metadata.get("error")
                if not reuse_succeeded:
                    # Sandbox expired or errored — clear dead entry
                    _sandbox_pool[key] = (None, lock)
                    logger.warning(
                        "[%s] Sandbox %s failed, creating new",
                        run_id,
                        existing_sandbox_id,
                    )

            if not reuse_succeeded:
                # Create new sandbox and keep it alive
                streamer = await client.chat_stream(
                    channel=channel,
                    thread_ts=thread_ts,
                    recipient_team_id=context.get("team_id"),
                    recipient_user_id=user_id,
                )
                await _stream_to_slack(
                    request,
                    run_id,
                    streamer,
                    client,
                    channel,
                    thread_ts,
                    keep_alive=True,
                    sandbox_id_out=sandbox_id_out,
                    binary_files=binary_files or None,
                )
                new_id = sandbox_id_out[0] if sandbox_id_out else None
                _sandbox_pool.pop(key, None)
                _sandbox_pool[key] = (new_id, lock)

        # Evict oldest entries if pool is too large (sandboxes auto-die via E2B timeout)
        while len(_sandbox_pool) > _MAX_SANDBOX_POOL:
            oldest_key = next(iter(_sandbox_pool))
            evicted_id, _ = _sandbox_pool.pop(oldest_key)
            if evicted_id:
                logger.debug("Evicted sandbox %s from pool (will auto-expire)", evicted_id)

        # Remove :eyes: reaction on completion
        with contextlib.suppress(Exception):
            await client.reactions_remove(channel=channel, timestamp=event["ts"], name="eyes")

    # ── 2. Assistant DM handler — conversational thread experience ──

    assistant = AsyncAssistant()

    @assistant.thread_started
    async def handle_thread_started(say, set_suggested_prompts):
        await say("Hi! I'm Sandstorm — I run code in secure sandboxes. What can I build for you?")
        await set_suggested_prompts(
            prompts=[
                {
                    "title": "Write and run code",
                    "message": "Create a Python script that...",
                },
                {
                    "title": "Analyze a file",
                    "message": "Analyze the attached file...",
                },
                {
                    "title": "Build something",
                    "message": "Build a REST API with...",
                },
            ]
        )

    @assistant.user_message
    async def handle_user_message(payload, client, say, set_status, context):
        channel_id = context.channel_id
        thread_ts = context.thread_ts
        user_id = payload.get("user", "unknown")
        bot_user_id = context.get("bot_user_id", "")
        prompt = payload.get("text", "")
        if not prompt.strip():
            await say("Please provide a prompt.")
            return

        await set_status("Spinning up sandbox...")
        run_id = uuid.uuid4().hex[:8]

        # Thread context + file downloads (same as @mention handler)
        messages = await _fetch_thread_messages(client, channel_id, thread_ts)
        thread_context = _gather_thread_context(messages, bot_user_id)
        text_files, binary_files = await _download_thread_files(client, messages, bot_user_id)

        full_prompt = prompt
        if thread_context:
            full_prompt = f"Thread context:\n{thread_context}\n\nUser request: {prompt}"

        all_files = list(text_files.keys()) + list(binary_files.keys())
        if all_files:
            file_list = "\n".join(f"- /home/user/{f}" for f in all_files)
            full_prompt += f"\n\nFiles available in your working directory:\n{file_list}"

        request = _build_query_request(full_prompt, text_files or None)

        # Sandbox reuse (same pool as @mention handler)
        key = (channel_id, thread_ts)
        if key not in _sandbox_pool:
            _sandbox_pool[key] = (None, asyncio.Lock())
        _, lock = _sandbox_pool[key]

        async with lock:
            existing_sandbox_id = _sandbox_pool[key][0]
            sandbox_id_out: list[str] = []
            reuse_succeeded = False
            if existing_sandbox_id:
                logger.info("[%s] DM reusing sandbox %s", run_id, existing_sandbox_id)
                streamer = await client.chat_stream(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    recipient_team_id=context.get("team_id"),
                    recipient_user_id=user_id,
                )
                metadata = await _stream_to_slack(
                    request,
                    run_id,
                    streamer,
                    client,
                    channel_id,
                    thread_ts,
                    set_status=set_status,
                    keep_alive=True,
                    sandbox_id=existing_sandbox_id,
                    binary_files=binary_files or None,
                )
                reuse_succeeded = not metadata.get("error")
                if not reuse_succeeded:
                    _sandbox_pool[key] = (None, lock)

            if not reuse_succeeded:
                streamer = await client.chat_stream(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    recipient_team_id=context.get("team_id"),
                    recipient_user_id=user_id,
                )
                await _stream_to_slack(
                    request,
                    run_id,
                    streamer,
                    client,
                    channel_id,
                    thread_ts,
                    set_status=set_status,
                    keep_alive=True,
                    sandbox_id_out=sandbox_id_out,
                    binary_files=binary_files or None,
                )
                new_id = sandbox_id_out[0] if sandbox_id_out else None
                _sandbox_pool.pop(key, None)
                _sandbox_pool[key] = (new_id, lock)

        # Evict oldest entries if pool is too large
        while len(_sandbox_pool) > _MAX_SANDBOX_POOL:
            oldest_key = next(iter(_sandbox_pool))
            evicted_id, _ = _sandbox_pool.pop(oldest_key)
            if evicted_id:
                logger.debug("Evicted sandbox %s from pool (will auto-expire)", evicted_id)

    app.use(assistant)

    # ── 3. Feedback action handlers ──

    async def _handle_feedback(ack, body, client, *, sentiment: str, emoji: str, label: str):
        await ack()
        run_id = body["actions"][0]["value"]
        user = body["user"]["id"]
        run_store.set_feedback(run_id, sentiment, user)

        # Replace buttons with confirmation
        message = body.get("message", {})
        channel = body["channel"]["id"]
        ts = message.get("ts")
        blocks = message.get("blocks", [])
        updated_blocks = [b for b in blocks if b.get("type") != "actions"]
        updated_blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"{emoji} <@{user}> {label}"}],
            }
        )
        if ts:
            await client.chat_update(
                channel=channel, ts=ts, blocks=updated_blocks, text="Feedback recorded"
            )

    @app.action("sandstorm_feedback_positive")
    async def handle_positive(ack, body, client):
        await _handle_feedback(
            ack, body, client, sentiment="positive", emoji="\U0001f44d", label="found this helpful"
        )

    @app.action("sandstorm_feedback_negative")
    async def handle_negative(ack, body, client):
        await _handle_feedback(
            ack,
            body,
            client,
            sentiment="negative",
            emoji="\U0001f44e",
            label="found this not helpful",
        )

    return app


# ── CLI entrypoints ───────────────────────────────────────────────────────────


def run_socket_mode(bot_token: str | None = None, app_token: str | None = None) -> None:
    """Start bot in Socket Mode (dev — no public URL needed)."""
    from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

    app = create_slack_app(bot_token=bot_token)
    app_token = app_token or os.environ.get("SLACK_APP_TOKEN")
    if not app_token:
        raise RuntimeError(
            "SLACK_APP_TOKEN is required for Socket Mode — set it in .env or pass via --app-token"
        )

    logger.info("Starting Sandstorm Slack bot in Socket Mode...")

    async def _start():
        handler = AsyncSocketModeHandler(app, app_token)
        await handler.start_async()

    asyncio.run(_start())


def run_http_mode(
    bot_token: str | None = None,
    signing_secret: str | None = None,
    host: str = "0.0.0.0",
    port: int = 3000,
) -> None:
    """Start bot in HTTP mode (production)."""
    import uvicorn
    from slack_bolt.adapter.starlette.async_handler import AsyncSlackRequestHandler
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    secret = signing_secret or os.environ.get("SLACK_SIGNING_SECRET")
    app = create_slack_app(bot_token=bot_token, signing_secret=secret)
    app_handler = AsyncSlackRequestHandler(app)

    async def endpoint(req: Request):
        return await app_handler.handle(req)

    async def health(req: Request):
        return JSONResponse({"status": "ok"})

    starlette_app = Starlette(
        routes=[
            Route("/slack/events", endpoint=endpoint, methods=["POST"]),
            Route("/health", endpoint=health, methods=["GET"]),
        ]
    )
    logger.info("Starting Sandstorm Slack bot in HTTP mode on %s:%d", host, port)
    uvicorn.run(starlette_app, host=host, port=port)
