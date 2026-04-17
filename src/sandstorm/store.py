import json
import logging
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

RunStatus = Literal["running", "completed", "error"]


@dataclass
class Run:
    id: str
    prompt: str
    model: str | None
    status: RunStatus
    started_at: str
    cost_usd: float | None = None
    num_turns: int | None = None
    duration_secs: float | None = None
    error: str | None = None
    files_count: int = 0
    feedback: str | None = None
    feedback_user: str | None = None
    # Untruncated, distinct from the 100-char display `prompt`; needed for ds replay.
    raw_prompt: str = ""
    agent_session_id: str | None = None
    sandbox_id: str | None = None
    team_id: str | None = None
    user_id: str | None = None
    channel_id: str | None = None
    thread_ts: str | None = None
    # Only the keys explicitly allowed by `_CONFIG_SNAPSHOT_KEYS` are written here;
    # env / secret / mcp_servers values are intentionally excluded to keep the
    # JSONL file free of credentials.
    config_snapshot: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# Whitelist of sandstorm.json / QueryRequest keys that are safe to snapshot into
# a Run record for `ds replay`. Widen with care: env maps and mcp_servers
# configs often carry secrets. `files` stays in because file contents were
# already persisted in the prompt; excluding them breaks replay reproducibility.
_CONFIG_SNAPSHOT_KEYS = frozenset({"model", "max_turns", "timeout", "allowed_tools", "files"})


def build_config_snapshot(source: dict | None) -> dict | None:
    """Return a filtered copy of `source` containing only replay-safe keys."""
    if not source:
        return None
    return {k: v for k, v in source.items() if k in _CONFIG_SNAPSHOT_KEYS}


class RunStore:
    """In-memory run store backed by a JSONL file for persistence."""

    def __init__(self, path: str | Path = ".sandstorm/runs.jsonl", maxlen: int = 200):
        self._path = Path(path)
        self._maxlen = maxlen
        self._runs: deque[Run] = deque(maxlen=maxlen)
        self._index: dict[str, Run] = {}
        self._load_from_file()
        self._maybe_compact_on_load()

    def _maybe_compact_on_load(self) -> None:
        """Rewrite the JSONL to the live in-deque set when it has grown past
        10x the in-memory cap. Every status transition appends a new line, so
        a long-running deployment accumulates stale records for runs that have
        already fallen out of the deque. Bounds the file without changing
        semantics or visible history in `list()`.
        """
        if not self._path.exists():
            return
        try:
            with self._path.open("rb") as f:
                line_count = sum(1 for _ in f)
        except OSError:
            return
        if line_count <= self._maxlen * 10:
            return
        try:
            tmp = self._path.with_suffix(self._path.suffix + ".compact")
            with tmp.open("w") as f:
                for run in self._runs:
                    f.write(json.dumps(run.to_dict()) + "\n")
            tmp.replace(self._path)
            logger.info(
                "RunStore: compacted %s (%d lines -> %d)",
                self._path,
                line_count,
                len(self._runs),
            )
        except OSError:
            logger.warning("RunStore: compact failed", exc_info=True)

    def create(
        self,
        id: str,
        prompt: str,
        model: str | None,
        files_count: int = 0,
        raw_prompt: str | None = None,
        sandbox_id: str | None = None,
        team_id: str | None = None,
        user_id: str | None = None,
        channel_id: str | None = None,
        thread_ts: str | None = None,
        config_snapshot: dict | None = None,
    ) -> Run:
        run = Run(
            id=id,
            prompt=prompt[:100],
            model=model,
            status="running",
            started_at=datetime.now(UTC).isoformat(),
            files_count=files_count,
            raw_prompt=raw_prompt if raw_prompt is not None else prompt,
            sandbox_id=sandbox_id,
            team_id=team_id,
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            config_snapshot=config_snapshot,
        )
        # If deque is full, evict the oldest and remove from index
        if len(self._runs) == self._maxlen:
            evicted = self._runs[0]
            self._index.pop(evicted.id, None)
        self._runs.append(run)
        self._index[run.id] = run
        return run

    def complete(
        self,
        id: str,
        cost_usd: float | None = None,
        num_turns: int | None = None,
        duration_secs: float | None = None,
        model: str | None = None,
        agent_session_id: str | None = None,
        sandbox_id: str | None = None,
    ) -> None:
        run = self._index.get(id)
        if run is None:
            logger.warning("RunStore.complete: unknown run id=%s", id)
            return
        run.status = "completed"
        run.cost_usd = cost_usd
        run.num_turns = num_turns
        run.duration_secs = duration_secs
        if model:
            run.model = model
        if agent_session_id:
            run.agent_session_id = agent_session_id
        if sandbox_id:
            run.sandbox_id = sandbox_id
        self._append_to_file(run)

    def fail(self, id: str, error: str, duration_secs: float | None = None) -> None:
        run = self._index.get(id)
        if run is None:
            logger.warning("RunStore.fail: unknown run id=%s", id)
            return
        run.status = "error"
        run.error = error
        run.duration_secs = duration_secs
        self._append_to_file(run)

    def set_feedback(self, id: str, feedback: str, user: str) -> None:
        run = self._index.get(id)
        if run is None:
            logger.warning("RunStore.set_feedback: unknown run id=%s", id)
            return
        run.feedback = feedback
        run.feedback_user = user
        self._append_to_file(run)

    def list(self, limit: int = 50) -> list[dict]:
        runs = list(self._runs)
        runs.reverse()  # newest first
        return [r.to_dict() for r in runs[:limit]]

    def get(self, run_id: str) -> Run | None:
        """Return the Run with this id, or None. O(1)."""
        return self._index.get(run_id)

    def find_most_recent(self, predicate: Callable[[Run], bool]) -> Run | None:
        """Return the most recent Run matching the predicate, or None."""
        for run in reversed(self._runs):
            if predicate(run):
                return run
        return None

    def find_thread_session(
        self, team_id: str | None, channel_id: str, thread_ts: str
    ) -> Run | None:
        """Return the most recent completed Run in this Slack thread, if any.

        Used by slack.py to pick up a prior agent_session_id (Agent SDK resume)
        and sandbox_id (E2B pause/resume) when the in-memory pool misses,
        including after a server restart.
        """
        return self.find_most_recent(
            lambda r: (
                r.team_id == team_id
                and r.channel_id == channel_id
                and r.thread_ts == thread_ts
                and r.status == "completed"
            )
        )

    def _append_to_file(self, run: Run) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a") as f:
                f.write(json.dumps(run.to_dict()) + "\n")
        except OSError:
            logger.warning("RunStore: failed to write to %s", self._path, exc_info=True)

    def _load_from_file(self) -> None:
        if not self._path.exists():
            return
        try:
            with self._path.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        run = Run(**data)
                        if run.id in self._index:
                            # Last-write-wins: update existing entry with latest state
                            existing = self._index[run.id]
                            for field in (
                                "status",
                                "cost_usd",
                                "num_turns",
                                "duration_secs",
                                "error",
                                "model",
                                "feedback",
                                "feedback_user",
                            ):
                                val = getattr(run, field)
                                if val is not None:
                                    setattr(existing, field, val)
                            continue
                        self._runs.append(run)
                        self._index[run.id] = run
                    except (json.JSONDecodeError, TypeError, KeyError):
                        logger.warning("RunStore: skipping malformed line in %s", self._path)
        except OSError:
            logger.warning("RunStore: failed to read %s", self._path, exc_info=True)
        # Rebuild index from deque to match maxlen eviction
        self._index = {r.id: r for r in self._runs}


run_store = RunStore()
