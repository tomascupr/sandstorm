import json
import logging
from collections import deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Run:
    id: str
    prompt: str
    model: str | None
    status: str  # "running", "completed", "error"
    started_at: str
    cost_usd: float | None = None
    num_turns: int | None = None
    duration_secs: float | None = None
    error: str | None = None
    files_count: int = 0
    feedback: str | None = None
    feedback_user: str | None = None
    # Untruncated prompt — needed for `ds replay` (distinct from the 100-char display `prompt`)
    raw_prompt: str = ""
    # Captured from runner.mjs on completion — enables Agent SDK session resume
    agent_session_id: str | None = None
    # Captured at sandbox creation — enables E2B pause/resume across Slack messages
    sandbox_id: str | None = None
    # Slack thread context — nullable for CLI/HTTP runs
    team_id: str | None = None
    user_id: str | None = None
    channel_id: str | None = None
    thread_ts: str | None = None
    # Snapshot of runtime config (model, allowed_tools, mcp_servers, files)
    # so replays can reproduce the original run deterministically
    config_snapshot: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class RunStore:
    """In-memory run store backed by a JSONL file for persistence."""

    def __init__(self, path: str | Path = ".sandstorm/runs.jsonl", maxlen: int = 200):
        self._path = Path(path)
        self._maxlen = maxlen
        self._runs: deque[Run] = deque(maxlen=maxlen)
        self._index: dict[str, Run] = {}
        self._load_from_file()

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
