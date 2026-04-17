"""User-scoped memory, JSONL-backed. Mirrors the RunStore shape in store.py.

Memories are append-only with tombstone records for deletes, so the storage file
stays simple (`.sandstorm/memories.jsonl`). The store is keyed on
`(team_id, user_id)` — there is no cross-workspace sharing. For CLI/HTTP runs
without a Slack team context, `team_id="__local__"` is the canonical default.

The agent never calls this as a tool — the host injects remembered content into
`system_prompt_append` at query time via `as_prompt_prefix()`.
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

logger = logging.getLogger(__name__)

_LOCAL_TEAM_ID = "__local__"
# Memories often contain credentials ("my openai key is sk-..."). Keep the
# on-disk file readable only by the owning user.
_PRIVATE_FILE_MODE = 0o600


@dataclass
class Memory:
    id: str
    team_id: str
    user_id: str
    text: str
    created_at: str  # ISO UTC
    deleted: bool = False  # tombstone for forget()

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
    def _scope(team_id: str | None, user_id: str | None) -> tuple[str, str]:
        return (team_id or _LOCAL_TEAM_ID, user_id or _LOCAL_TEAM_ID)

    def remember(self, team_id: str | None, user_id: str | None, text: str) -> Memory:
        team, user = self._scope(team_id, user_id)
        memory = Memory(
            id=uuid.uuid4().hex,
            team_id=team,
            user_id=user,
            text=text.strip(),
            created_at=datetime.now(UTC).isoformat(),
        )
        if len(self._memories) == self._maxlen:
            evicted = self._memories[0]
            self._index.pop(evicted.id, None)
        self._memories.append(memory)
        self._index[memory.id] = memory
        self._append_to_file(memory)
        return memory

    def forget(self, team_id: str | None, user_id: str | None, substring: str) -> int:
        """Tombstone any live memory whose text contains `substring` (case-insensitive).
        Returns number of memories deleted."""
        team, user = self._scope(team_id, user_id)
        needle = substring.lower()
        deleted = 0
        for memory in list(self._memories):
            if (
                not memory.deleted
                and memory.team_id == team
                and memory.user_id == user
                and needle in memory.text.lower()
            ):
                memory.deleted = True
                self._append_to_file(memory)
                deleted += 1
        return deleted

    def list(self, team_id: str | None, user_id: str | None) -> list[Memory]:
        team, user = self._scope(team_id, user_id)
        return [
            m for m in self._memories if not m.deleted and m.team_id == team and m.user_id == user
        ]

    def as_prompt_prefix(self, team_id: str | None, user_id: str | None) -> str:
        """Format memories as a bullet list suitable for prepending to system_prompt_append.
        Returns an empty string when no memories exist — callers can safely concatenate."""
        memories = self.list(team_id, user_id)
        if not memories:
            return ""
        bullets = "\n".join(f"- {m.text}" for m in memories)
        return f"User memory (persisted across sessions):\n{bullets}\n\n"

    def _append_to_file(self, memory: Memory) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            new_file = not self._path.exists()
            with self._path.open("a") as f:
                f.write(json.dumps(memory.to_dict()) + "\n")
            if new_file:
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
                        self._memories.append(memory)
                        self._index[memory.id] = memory
                    except (json.JSONDecodeError, TypeError, KeyError):
                        logger.warning("MemoryStore: skipping malformed line in %s", self._path)
        except OSError:
            logger.warning("MemoryStore: failed to read %s", self._path, exc_info=True)
        self._index = {m.id: m for m in self._memories}


memory_store = MemoryStore()
