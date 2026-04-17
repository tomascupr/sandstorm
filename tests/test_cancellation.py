"""Tests for the in-memory cancellation primitive."""

from __future__ import annotations

import asyncio

from sandstorm.cancellation import (
    _active_runs,
    is_cancelled,
    is_registered,
    register_run,
    request_cancellation,
    unregister_run,
)


class TestRegistry:
    def setup_method(self) -> None:
        _active_runs.clear()

    def test_register_creates_live_event(self):
        register_run("r1")
        assert is_registered("r1")
        assert is_cancelled("r1") is False

    def test_unregister_removes_event(self):
        register_run("r1")
        unregister_run("r1")
        assert is_registered("r1") is False
        assert is_cancelled("r1") is False

    def test_unregister_unknown_is_noop(self):
        unregister_run("never-existed")  # should not raise


class TestRequestCancellation:
    def setup_method(self) -> None:
        _active_runs.clear()

    def test_request_on_live_run_returns_true(self):
        register_run("r1")
        assert request_cancellation("r1") is True
        assert is_cancelled("r1") is True

    def test_request_on_unknown_returns_false(self):
        assert request_cancellation("nope") is False

    def test_event_can_be_awaited(self):
        async def _go() -> bool:
            event = register_run("r1")

            # Schedule cancellation after a zero-sleep yield
            async def _cancel_soon() -> None:
                await asyncio.sleep(0)
                request_cancellation("r1")

            asyncio.create_task(_cancel_soon())
            await asyncio.wait_for(event.wait(), timeout=1.0)
            return event.is_set()

        assert asyncio.run(_go()) is True


class TestRunStoreHelper:
    def test_find_in_flight_run(self, tmp_path):
        from sandstorm.store import RunStore

        store = RunStore(path=tmp_path / "runs.jsonl")
        store.create(
            id="r1",
            prompt="x",
            model=None,
            team_id="T1",
            channel_id="C1",
            thread_ts="1.0",
        )
        assert store.find_in_flight_run("T1", "C1", "1.0").id == "r1"
        store.complete(id="r1")
        # After complete, status transitions to "completed" -> not in-flight
        assert store.find_in_flight_run("T1", "C1", "1.0") is None
