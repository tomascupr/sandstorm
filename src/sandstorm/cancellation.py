"""In-memory cancellation primitive for in-flight agent runs.

A run registers an `asyncio.Event` at start. The streaming generator in
`sandbox.py` polls `is_cancelled(run_id)` between SDK yields; when set,
the loop exits and the finally block kills the sandbox. Surfaces:

- HTTP: ``POST /runs/<run_id>/cancel``
- Slack: ``/cancel`` slash command
- CLI: ``ds cancel <run_id>``
- App Home: ``[Cancel]`` button

No persistence: a server restart forgets in-flight runs. That's fine,
because an in-flight run can't survive a restart anyway.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

# Module-level registry. Keys are run_ids; values are asyncio.Events that,
# when set, signal the streaming generator to break.
_active_runs: dict[str, asyncio.Event] = {}


def register_run(run_id: str) -> asyncio.Event:
    """Return a fresh cancellation event for this run and register it."""
    event = asyncio.Event()
    _active_runs[run_id] = event
    return event


def unregister_run(run_id: str) -> None:
    """Remove a run's cancellation event. Safe to call multiple times."""
    _active_runs.pop(run_id, None)


def request_cancellation(run_id: str) -> bool:
    """Signal cancellation for the named run.

    Returns True when the run was live and got cancelled; False when the
    run id is not registered (already completed, failed, or never existed).
    """
    event = _active_runs.get(run_id)
    if event is None:
        return False
    event.set()
    logger.info("Cancellation requested for run %s", run_id)
    return True


def is_cancelled(run_id: str) -> bool:
    """Cheap O(1) check for the streaming loop."""
    event = _active_runs.get(run_id)
    return event is not None and event.is_set()


def is_registered(run_id: str) -> bool:
    """True when the run has a registered cancellation event."""
    return run_id in _active_runs
