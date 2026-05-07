"""Shared platform-agnostic core for chat integrations.

Contains utilities, protocols, and orchestration shared across Slack,
Google Chat, and future chat platform adapters.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import time
from collections.abc import Callable

from .models import QueryRequest
from .sandbox import run_agent_in_sandbox
from .store import build_config_snapshot

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 50 * 1024 * 1024

BINARY_MIME_PREFIXES = (
    "image/",
    "audio/",
    "video/",
    "application/pdf",
    "application/zip",
    "application/vnd.openxmlformats-",
    "application/vnd.ms-",
    "application/msword",
    "application/x-7z-compressed",
    "application/x-rar-compressed",
    "application/x-tar",
    "application/gzip",
    "application/octet-stream",
)


def build_query_request(
    prompt: str,
    files: dict[str, str] | None = None,
    team_id: str | None = None,
    user_id: str | None = None,
    model: str | None = None,
    channel_id: str | None = None,
) -> QueryRequest:
    """Build QueryRequest from prompt, deferring model/timeout to sandstorm.json."""
    return QueryRequest(
        prompt=prompt,
        model=model,
        timeout=None,
        files=files,
        output_format={},
        anthropic_api_key=None,
        e2b_api_key=None,
        openrouter_api_key=None,
        max_turns=None,
        team_id=team_id,
        user_id=user_id,
        channel_id=channel_id,
    )


def gather_thread_context(
    messages: list[dict],
    bot_user_id: str,
    *,
    user_names: dict[str, str] | None = None,
) -> str:
    """Format thread messages into a context string."""
    lines: list[str] = []
    for msg in messages:
        user = msg.get("user", "unknown")
        text = msg.get("text", "").strip()

        if user == bot_user_id:
            if text:
                lines.append(f"[Sandstorm] {text}")
            continue

        display = user_names.get(user, user) if user_names else user

        if text:
            lines.append(f"[{display}] {text}")

        for f in msg.get("files", []):
            name = f.get("name", "unknown")
            mimetype = f.get("mimetype", "unknown")
            size = f.get("size", 0)
            size_kb = size / 1024
            lines.append(f"[{display}] [attached: {name} ({mimetype}, {size_kb:.0f}KB)]")

    return "\n".join(lines)


def unique_filename(name: str, seen: set[str]) -> str:
    """Return a unique filename, appending _1, _2, etc. for duplicates."""
    if name not in seen:
        seen.add(name)
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    for i in range(1, 100):
        candidate = f"{stem}_{i}.{ext}" if ext else f"{stem}_{i}"
        if candidate not in seen:
            seen.add(candidate)
            return candidate
    return name


MAX_SANDBOX_POOL = 1000


class SandboxPoolManager:
    """Thread-safe sandbox reuse pool with LRU eviction."""

    def __init__(self, max_size: int = MAX_SANDBOX_POOL):
        self._max_size = max_size
        self._pool: dict[tuple[str, str, str], tuple[str | None, asyncio.Lock]] = {}

    async def get_or_create(
        self, tenant: str, channel: str, thread_ts: str
    ) -> tuple[str | None, asyncio.Lock]:
        key = (tenant, channel, thread_ts)
        if key not in self._pool:
            self._pool[key] = (None, asyncio.Lock())
        return self._pool[key]

    def update(self, tenant: str, channel: str, thread_ts: str, sandbox_id: str | None) -> None:
        key = (tenant, channel, thread_ts)
        if key in self._pool:
            _, lock = self._pool[key]
            self._pool[key] = (sandbox_id, lock)

    def clear(self, tenant: str, channel: str, thread_ts: str) -> None:
        key = (tenant, channel, thread_ts)
        if key in self._pool:
            _, lock = self._pool[key]
            self._pool[key] = (None, lock)

    def set_initial(
        self, tenant: str, channel: str, thread_ts: str, sandbox_id: str | None
    ) -> None:
        key = (tenant, channel, thread_ts)
        if key not in self._pool:
            self._pool[key] = (sandbox_id, asyncio.Lock())

    def has_key(self, tenant: str, channel: str, thread_ts: str) -> bool:
        return (tenant, channel, thread_ts) in self._pool

    def evict_if_needed(self) -> None:
        while len(self._pool) > self._max_size:
            oldest_key = next(iter(self._pool))
            evicted_id, _ = self._pool.pop(oldest_key)
            if evicted_id:
                logger.debug("Evicted sandbox %s from pool", evicted_id)

    def size(self) -> int:
        return len(self._pool)


class StreamBridge:
    """Consume run_agent_in_sandbox() events and dispatch to a streamer.

    The streamer must implement:
      async append(*, markdown_text: str) -> None
      async stop(blocks: list[dict] | None = None) -> None
    """

    def __init__(self, streamer, *, run_store):
        self._streamer = streamer
        self._run_store = run_store

    async def run(
        self,
        request,
        run_id: str,
        client,
        channel: str,
        thread_ts: str,
        set_status: Callable | None = None,
        *,
        keep_alive: bool = False,
        sandbox_id: str | None = None,
        sandbox_id_out: list[str] | None = None,
        binary_files: dict[str, bytes] | None = None,
        build_footer: Callable | None = None,
        upload_file: Callable | None = None,
    ) -> dict:
        metadata: dict = {
            "model": None, "cost_usd": None, "num_turns": None,
            "duration_secs": None, "error": None, "agent_session_id": None,
        }
        start = time.monotonic()
        stopped = False
        has_streamed_text = False

        self._run_store.create(
            id=run_id,
            prompt=request.prompt,
            model=request.model,
            files_count=len(request.files) if request.files else 0,
            raw_prompt=request.prompt,
            team_id=request.team_id,
            user_id=request.user_id,
            channel_id=channel,
            thread_ts=thread_ts,
            sandbox_id=sandbox_id,
            config_snapshot=build_config_snapshot({
                "model": request.model,
                "allowed_tools": request.allowed_tools,
                "timeout": request.timeout,
                "files": request.files,
            }),
        )

        try:
            async for line in run_agent_in_sandbox(
                request, run_id, keep_alive=keep_alive,
                sandbox_id=sandbox_id, sandbox_id_out=sandbox_id_out,
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
                    metadata["agent_session_id"] = (
                        event.get("session_id") or metadata["agent_session_id"]
                    )
                    if set_status:
                        await set_status(f"Running agent on {model}...")

                elif event_type == "assistant":
                    message = event.get("message", {})
                    for block in message.get("content", []):
                        if block.get("type") == "text":
                            text = block["text"]
                            if text:
                                prefix = "\n\n" if has_streamed_text else ""
                                try:
                                    await self._streamer.append(markdown_text=prefix + text)
                                    has_streamed_text = True
                                    logger.info("[%s] Streamed %d chars", run_id, len(text))
                                except Exception:
                                    logger.error("[%s] streamer.append failed", run_id, exc_info=True)
                        elif block.get("type") == "tool_use":
                            tool_name = block.get("name", "unknown")
                            logger.info("[%s] Tool: %s", run_id, tool_name)
                            if set_status:
                                await set_status(f"Using {tool_name}...")
                            else:
                                try:
                                    await self._streamer.append(
                                        markdown_text=f"\n_:hammer_and_wrench: {tool_name}_\n"
                                    )
                                    has_streamed_text = True
                                except Exception:
                                    logger.error(
                                        "[%s] streamer.append (tool crumb) failed",
                                        run_id, exc_info=True,
                                    )

                elif event_type == "result":
                    cost = event.get("total_cost_usd")
                    metadata["cost_usd"] = cost if cost is not None else event.get("cost_usd")
                    metadata["num_turns"] = event.get("num_turns")
                    metadata["duration_secs"] = round(time.monotonic() - start, 1)
                    metadata["model"] = event.get("model") or metadata["model"]
                    logger.info(
                        "[%s] Result: turns=%s cost=%s",
                        run_id, metadata["num_turns"], metadata["cost_usd"],
                    )

                    footer_blocks = build_footer(run_id, metadata) if build_footer else None
                    try:
                        await self._streamer.stop(blocks=footer_blocks)
                        stopped = True
                        logger.info("[%s] Stream stopped with footer", run_id)
                    except Exception:
                        logger.error("[%s] streamer.stop failed", run_id, exc_info=True)

                    metadata["agent_session_id"] = (
                        event.get("session_id") or metadata["agent_session_id"]
                    )
                    if metadata["agent_session_id"] is None:
                        logger.info(
                            "[%s] No agent_session_id captured — next thread message "
                            "will not resume the session",
                            run_id,
                        )
                    self._run_store.complete(
                        run_id,
                        cost_usd=metadata["cost_usd"],
                        num_turns=metadata["num_turns"],
                        duration_secs=metadata["duration_secs"],
                        model=metadata["model"],
                        agent_session_id=metadata["agent_session_id"],
                    )

                elif event_type == "error":
                    error_msg = event.get("error", "Unknown error")
                    metadata["error"] = error_msg
                    metadata["duration_secs"] = round(time.monotonic() - start, 1)
                    logger.error("[%s] Agent error: %s", run_id, error_msg)

                    try:
                        await self._streamer.append(markdown_text=f"\n:warning: Error: {error_msg}")
                        await self._streamer.stop()
                        stopped = True
                    except Exception:
                        logger.error("[%s] streamer.stop (error) failed", run_id, exc_info=True)

                    self._run_store.fail(run_id, error_msg, metadata["duration_secs"])

                elif event_type == "file":
                    file_name = event.get("name", "file")
                    file_title = event.get("relative_path") or file_name
                    file_data_b64 = event.get("data")
                    if file_data_b64 and upload_file:
                        try:
                            file_data = base64.b64decode(file_data_b64)
                            await upload_file(
                                channel=channel,
                                thread_ts=thread_ts,
                                content=file_data,
                                filename=file_name,
                                title=file_title,
                            )
                            logger.info(
                                "[%s] Uploaded file %s (%d bytes)",
                                run_id, file_title, len(file_data),
                            )
                        except Exception:
                            logger.error(
                                "[%s] Failed to upload %s",
                                run_id, file_name, exc_info=True,
                            )

                elif event_type in ("user", "stderr", "warning"):
                    logger.debug("[%s] %s", run_id, event_type)

        except Exception as exc:
            metadata["error"] = str(exc)
            metadata["duration_secs"] = round(time.monotonic() - start, 1)
            logger.error("[%s] Stream error: %s", run_id, exc, exc_info=True)
            self._run_store.fail(run_id, str(exc), metadata["duration_secs"])
        finally:
            if not stopped:
                with contextlib.suppress(Exception):
                    await self._streamer.stop()

        return metadata
