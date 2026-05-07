"""Shared platform-agnostic core for chat integrations.

Contains utilities, protocols, and orchestration shared across Slack,
Google Chat, and future chat platform adapters.
"""

from __future__ import annotations

import asyncio
import logging
from .models import QueryRequest

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
