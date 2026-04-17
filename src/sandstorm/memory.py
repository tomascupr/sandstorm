"""User-scoped memory, JSONL-backed. Mirrors the RunStore shape in store.py.

Memories are append-only with tombstone records for deletes, so the storage file
stays simple (`.sandstorm/memories.jsonl`). v0.9.1 extends the original
single-level (team_id, user_id) design to three scopes:

- ``user``: personal memory for (team_id, user_id) - original behaviour
- ``channel``: memory shared across users in a single Slack channel
  (team_id, channel_id)
- ``team``: memory shared across everyone in the Slack tenant (team_id)

The agent sees all three concatenated in ``as_prompt_prefix`` (team first,
channel second, user third) so the most-specific context lands closest to
the prompt. Back-compat: rows without ``scope`` / ``channel_id`` load as
``scope="user"`` via dataclass defaults.
"""

import contextlib
import json
import logging
import os
import uuid
from collections import deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

_LOCAL_TEAM_ID = "__local__"
# Memories often contain credentials ("my openai key is sk-..."). Keep the
# on-disk file readable only by the owning user.
_PRIVATE_FILE_MODE = 0o600

MemoryScope = Literal["user", "channel", "team"]


@dataclass
class Memory:
    id: str
    team_id: str
    user_id: str
    text: str
    created_at: str  # ISO UTC
    deleted: bool = False  # tombstone for forget()
    scope: MemoryScope = "user"
    channel_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class MemoryStore:
    """In-memory deque + JSONL for persistence. Tombstone records encode deletes."""

    def __init__(self, path: str | Path = ".sandstorm/memories.jsonl", maxlen: int = 10_000):
        self._path = Path(path)
        self._maxlen = maxlen
        self._memories: deque[Memory] = deque(maxlen=maxlen)
        self._index: dict[str, Memory] = {}
        self._load_from_file()

    @staticmethod
    def _normalize_team_user(team_id: str | None, user_id: str | None) -> tuple[str, str]:
        return (team_id or _LOCAL_TEAM_ID, user_id or _LOCAL_TEAM_ID)

    def _scope_matches(
        self,
        memory: Memory,
        *,
        team_id: str | None,
        user_id: str | None,
        channel_id: str | None,
        scope: MemoryScope,
    ) -> bool:
        """True when `memory` belongs to the requested (team, user, channel, scope)."""
        team, user = self._normalize_team_user(team_id, user_id)
        if memory.scope != scope:
            return False
        if memory.team_id != team:
            return False
        if scope == "team":
            return True
        if scope == "channel":
            return memory.channel_id == channel_id
        # user scope
        return memory.user_id == user

    def remember(
        self,
        team_id: str | None,
        user_id: str | None,
        text: str,
        *,
        scope: MemoryScope = "user",
        channel_id: str | None = None,
    ) -> Memory:
        team, user = self._normalize_team_user(team_id, user_id)
        if scope == "channel" and not channel_id:
            raise ValueError("channel-scoped memory requires channel_id")
        memory = Memory(
            id=uuid.uuid4().hex,
            team_id=team,
            user_id=user,
            text=text.strip(),
            created_at=datetime.now(UTC).isoformat(),
            scope=scope,
            channel_id=channel_id if scope == "channel" else None,
        )
        if len(self._memories) == self._maxlen:
            evicted = self._memories[0]
            self._index.pop(evicted.id, None)
        self._memories.append(memory)
        self._index[memory.id] = memory
        self._append_to_file(memory)
        return memory

    def forget(
        self,
        team_id: str | None,
        user_id: str | None,
        substring: str,
        *,
        scope: MemoryScope | None = None,
        channel_id: str | None = None,
    ) -> int:
        """Tombstone any live memory whose text contains `substring`.

        When `scope` is None, matches across user + channel + team scopes the
        caller can see. Matching is case-insensitive.
        """
        team, user = self._normalize_team_user(team_id, user_id)
        needle = substring.lower()
        deleted = 0
        target_scopes: tuple[MemoryScope, ...] = (
            (scope,) if scope is not None else ("user", "channel", "team")
        )
        for memory in list(self._memories):
            if memory.deleted:
                continue
            if memory.scope not in target_scopes:
                continue
            if memory.team_id != team:
                continue
            if memory.scope == "user" and memory.user_id != user:
                continue
            if memory.scope == "channel" and memory.channel_id != channel_id:
                continue
            if needle not in memory.text.lower():
                continue
            memory.deleted = True
            self._append_to_file(memory)
            deleted += 1
        return deleted

    def list(
        self,
        team_id: str | None,
        user_id: str | None,
        *,
        scope: MemoryScope | None = None,
        channel_id: str | None = None,
    ) -> list[Memory]:
        """List live memories visible to (team, user, channel).

        When `scope` is None, returns the combined view: team + channel + user
        in that order (most general first, most specific last).
        """
        if scope is not None:
            return [
                m
                for m in self._memories
                if not m.deleted
                and self._scope_matches(
                    m,
                    team_id=team_id,
                    user_id=user_id,
                    channel_id=channel_id,
                    scope=scope,
                )
            ]
        # Combined view: team + channel + user
        out: list[Memory] = []
        for target_scope in ("team", "channel", "user"):
            if target_scope == "channel" and not channel_id:
                continue
            out.extend(
                m
                for m in self._memories
                if not m.deleted
                and self._scope_matches(
                    m,
                    team_id=team_id,
                    user_id=user_id,
                    channel_id=channel_id,
                    scope=target_scope,  # type: ignore[arg-type]
                )
            )
        return out

    def as_prompt_prefix(
        self,
        team_id: str | None,
        user_id: str | None,
        channel_id: str | None = None,
    ) -> str:
        """Format memories as a bullet list suitable for prepending to system_prompt_append.

        Returns an empty string when no memories exist. The order is team,
        channel, user — project-level append lands after this, so the most
        specific context is closest to the prompt.
        """
        memories = self.list(team_id, user_id, channel_id=channel_id)  # combined view
        if not memories:
            return ""
        bullets = "\n".join(f"- {m.text}" for m in memories)
        return f"User memory (persisted across sessions):\n{bullets}\n\n"

    def _append_to_file(self, memory: Memory) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a") as f:
                f.write(json.dumps(memory.to_dict()) + "\n")
            # chmod is idempotent and cheap; applying every write avoids a
            # TOCTOU window between file creation and the permissions fix.
            with contextlib.suppress(OSError):
                os.chmod(self._path, _PRIVATE_FILE_MODE)
        except OSError:
            logger.warning("MemoryStore: failed to write to %s", self._path, exc_info=True)

    def _load_from_file(self) -> None:
        if not self._path.exists():
            return
        try:
            with self._path.open() as f:
                for raw in f:
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        memory = Memory(**data)
                        # Tombstone records overwrite the live copy (last-write-wins)
                        if memory.id in self._index:
                            self._index[memory.id].deleted = memory.deleted
                            continue
                        # A tombstone for an id that has been evicted from the
                        # deque must not re-enter storage; it would burn a slot
                        # and surface as a "deleted" entry in list() callers.
                        if memory.deleted:
                            continue
                        self._memories.append(memory)
                        self._index[memory.id] = memory
                    except (json.JSONDecodeError, TypeError, KeyError):
                        logger.warning("MemoryStore: skipping malformed line in %s", self._path)
        except OSError:
            logger.warning("MemoryStore: failed to read %s", self._path, exc_info=True)
        self._index = {m.id: m for m in self._memories}


memory_store = MemoryStore()
