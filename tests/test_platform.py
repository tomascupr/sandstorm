"""Tests for the shared platform core (platform.py)."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

from sandstorm.platform import (
    build_query_request,
    gather_thread_context,
    unique_filename,
)
import pytest


@pytest.fixture(autouse=True)
def _set_required_env_vars(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.setenv("E2B_API_KEY", "e2b-test-key")


class TestBuildQueryRequest:
    def test_uses_env_defaults(self):
        request = build_query_request("hello world")
        assert request.prompt == "hello world"
        assert request.timeout is None
        assert request.model is None
        assert request.output_format == {}

    def test_attaches_files(self):
        files = {"data.csv": "a,b\n1,2"}
        request = build_query_request("analyze this", files)
        assert request.files == {"data.csv": "a,b\n1,2"}

    def test_scoped_memory_fields_passthrough(self):
        request = build_query_request(
            "hi", team_id="T1", user_id="U1", model="claude-haiku-4-5-20251001"
        )
        assert request.team_id == "T1"
        assert request.user_id == "U1"
        assert request.model == "claude-haiku-4-5-20251001"


class TestGatherThreadContext:
    def test_formats_thread_messages(self):
        messages = [
            {"user": "U001", "text": "Hey there"},
            {"user": "BBOT", "text": "Working on it..."},
        ]
        result = gather_thread_context(messages, "BBOT")
        assert "[U001] Hey there" in result
        assert "[Sandstorm] Working on it..." in result

    def test_includes_file_attachments(self):
        messages = [
            {
                "user": "U001",
                "text": "",
                "files": [{"name": "data.csv", "mimetype": "text/csv", "size": 15360}],
            },
        ]
        result = gather_thread_context(messages, "BBOT")
        assert "[attached: data.csv (text/csv, 15KB)]" in result

    def test_empty_messages(self):
        result = gather_thread_context([], "BBOT")
        assert result == ""

    def test_uses_display_names_when_provided(self):
        messages = [{"user": "U001", "text": "Hey there"}]
        user_names = {"U001": "Alice"}
        result = gather_thread_context(messages, "BBOT", user_names=user_names)
        assert "[Alice] Hey there" in result


class TestUniqueFilename:
    def test_first_use_unchanged(self):
        seen: set[str] = set()
        assert unique_filename("file.txt", seen) == "file.txt"

    def test_duplicate_gets_suffix(self):
        seen: set[str] = set()
        unique_filename("file.txt", seen)
        assert unique_filename("file.txt", seen) == "file_1.txt"

    def test_no_extension(self):
        seen: set[str] = set()
        unique_filename("README", seen)
        assert unique_filename("README", seen) == "README_1"


import asyncio
from sandstorm.platform import SandboxPoolManager


class TestStreamBridge:
    def _make_async_generator(self, events: list[str]):
        async def gen(request, request_id="", **kwargs):
            for event in events:
                yield event
        return gen

    def test_assistant_text_dispatched(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        monkeypatch.setenv("E2B_API_KEY", "e2b-test-key")
        from sandstorm.platform import StreamBridge
        events = [
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello"}]}}),
            json.dumps({"type": "result", "subtype": "end_turn", "num_turns": 1, "total_cost_usd": 0.01, "model": "sonnet"}),
        ]
        gen = self._make_async_generator(events)
        streamer = AsyncMock()
        streamer.append = AsyncMock()
        streamer.stop = AsyncMock()
        from sandstorm.store import RunStore
        request = build_query_request("test")
        bridge = StreamBridge(streamer, run_store=RunStore(path=tmp_path / "runs.jsonl"))

        with patch("sandstorm.platform.run_agent_in_sandbox", gen):
            result = asyncio.run(bridge.run(request, "run1", AsyncMock(), "C001", "ts1"))

        streamer.append.assert_called()
        streamer.stop.assert_called()
        assert result["model"] == "sonnet"
        assert result["cost_usd"] == 0.01

    def test_error_event_records_failure(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        monkeypatch.setenv("E2B_API_KEY", "e2b-test-key")
        from sandstorm.platform import StreamBridge
        events = [json.dumps({"type": "error", "error": "Sandbox timeout"})]
        gen = self._make_async_generator(events)
        streamer = AsyncMock()
        streamer.append = AsyncMock()
        streamer.stop = AsyncMock()
        from sandstorm.store import RunStore
        request = build_query_request("test")
        bridge = StreamBridge(streamer, run_store=RunStore(path=tmp_path / "runs.jsonl"))

        with patch("sandstorm.platform.run_agent_in_sandbox", gen):
            result = asyncio.run(bridge.run(request, "run2", AsyncMock(), "C001", "ts1"))

        assert result["error"] == "Sandbox timeout"


class TestSandboxPoolManager:
    def test_get_or_create_returns_none_for_new_key(self):
        pool = SandboxPoolManager(max_size=10)
        sandbox_id, lock = asyncio.run(pool.get_or_create("tenant", "chan", "ts"))
        assert sandbox_id is None
        assert lock is not None

    def test_update_stores_sandbox_id(self):
        pool = SandboxPoolManager(max_size=10)
        asyncio.run(pool.get_or_create("tenant", "chan", "ts"))
        pool.update("tenant", "chan", "ts", "sbx-123")
        sandbox_id, _ = asyncio.run(pool.get_or_create("tenant", "chan", "ts"))
        assert sandbox_id == "sbx-123"

    def test_clear_resets_sandbox_id(self):
        pool = SandboxPoolManager(max_size=10)
        asyncio.run(pool.get_or_create("tenant", "chan", "ts"))
        pool.update("tenant", "chan", "ts", "sbx-123")
        pool.clear("tenant", "chan", "ts")
        sandbox_id, _ = asyncio.run(pool.get_or_create("tenant", "chan", "ts"))
        assert sandbox_id is None

    def test_evicts_oldest_when_full(self):
        pool = SandboxPoolManager(max_size=2)
        asyncio.run(pool.get_or_create("t", "c", "ts1"))
        pool.update("t", "c", "ts1", "sbx-1")
        asyncio.run(pool.get_or_create("t", "c", "ts2"))
        pool.update("t", "c", "ts2", "sbx-2")
        # Adding a third should evict the first
        asyncio.run(pool.get_or_create("t", "c", "ts3"))
        pool.evict_if_needed()
        assert pool.size() <= 2
