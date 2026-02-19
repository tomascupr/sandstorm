"""Tests for the Slack bot integration."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

slack_bolt = pytest.importorskip("slack_bolt")

from sandstorm.slack import (  # noqa: E402
    _build_metadata_blocks,
    _build_query_request,
    _download_thread_files,
    _fetch_thread_messages,
    _gather_thread_context,
    _stream_to_slack,
)
from sandstorm.store import RunStore  # noqa: E402


@pytest.fixture(autouse=True)
def _set_required_env_vars(monkeypatch):
    """Provide default API keys so QueryRequest validator passes."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.setenv("E2B_API_KEY", "e2b-test-key")


class TestBuildMetadataBlocks:
    def test_returns_context_and_actions_blocks(self):
        blocks = _build_metadata_blocks("abc123", "sonnet", 0.0234, 3, 12.3)
        assert len(blocks) == 2
        assert blocks[0]["type"] == "context"
        assert blocks[1]["type"] == "actions"

    def test_context_contains_all_metadata(self):
        blocks = _build_metadata_blocks("abc123", "sonnet", 0.0234, 3, 12.3)
        text = blocks[0]["elements"][0]["text"]
        assert "Model: sonnet" in text
        assert "Turns: 3" in text
        assert "Cost: $0.0234" in text
        assert "Duration: 12.3s" in text

    def test_actions_contain_feedback_buttons(self):
        blocks = _build_metadata_blocks("abc123", "sonnet", 0.01, 1, 5.0)
        actions = blocks[1]["elements"]
        assert len(actions) == 2
        assert actions[0]["action_id"] == "sandstorm_feedback_positive"
        assert actions[0]["value"] == "abc123"
        assert actions[1]["action_id"] == "sandstorm_feedback_negative"
        assert actions[1]["value"] == "abc123"

    def test_handles_none_values(self):
        blocks = _build_metadata_blocks("abc123", None, None, None, None)
        # Should still have actions block, context may be absent
        assert any(b["type"] == "actions" for b in blocks)

    def test_no_context_block_when_all_none(self):
        blocks = _build_metadata_blocks("abc123", None, None, None, None)
        # Only actions block when no metadata
        assert len(blocks) == 1
        assert blocks[0]["type"] == "actions"


class TestBuildQueryRequest:
    def test_uses_env_defaults(self):
        request = _build_query_request("hello world")
        assert request.prompt == "hello world"
        assert request.timeout == 300
        assert request.model is None

    def test_uses_sandstorm_slack_model_env(self, monkeypatch):
        monkeypatch.setenv("SANDSTORM_SLACK_MODEL", "opus")
        request = _build_query_request("test")
        assert request.model == "opus"

    def test_uses_sandstorm_slack_timeout_env(self, monkeypatch):
        monkeypatch.setenv("SANDSTORM_SLACK_TIMEOUT", "600")
        request = _build_query_request("test")
        assert request.timeout == 600

    def test_invalid_timeout_falls_back_to_300(self, monkeypatch):
        monkeypatch.setenv("SANDSTORM_SLACK_TIMEOUT", "not-a-number")
        request = _build_query_request("test")
        assert request.timeout == 300

    def test_attaches_files(self):
        files = {"data.csv": "a,b\n1,2"}
        request = _build_query_request("analyze this", files)
        assert request.files == {"data.csv": "a,b\n1,2"}


class TestFetchThreadMessages:
    def test_returns_messages(self):
        client = AsyncMock()
        client.conversations_replies = AsyncMock(
            return_value={"messages": [{"user": "U001", "text": "hello"}]}
        )
        result = asyncio.run(_fetch_thread_messages(client, "C001", "1234.5678"))
        assert len(result) == 1
        assert result[0]["text"] == "hello"

    def test_paginates_with_cursor(self):
        client = AsyncMock()
        client.conversations_replies = AsyncMock(
            side_effect=[
                {
                    "messages": [{"user": "U001", "text": "page1"}],
                    "response_metadata": {"next_cursor": "cursor_abc"},
                },
                {
                    "messages": [{"user": "U002", "text": "page2"}],
                },
            ]
        )
        result = asyncio.run(_fetch_thread_messages(client, "C001", "1234.5678"))
        assert len(result) == 2
        assert result[0]["text"] == "page1"
        assert result[1]["text"] == "page2"
        assert client.conversations_replies.call_count == 2
        # Second call should include cursor
        _, kwargs = client.conversations_replies.call_args
        assert kwargs["cursor"] == "cursor_abc"

    def test_handles_api_error(self):
        client = AsyncMock()
        client.conversations_replies = AsyncMock(side_effect=Exception("API error"))
        result = asyncio.run(_fetch_thread_messages(client, "C001", "1234.5678"))
        assert result == []


class TestGatherThreadContext:
    @pytest.fixture
    def messages(self):
        return [
            {"user": "U001", "text": "Hey, this CSV has duplicates"},
            {
                "user": "U001",
                "text": "",
                "files": [
                    {
                        "name": "data.csv",
                        "mimetype": "text/csv",
                        "size": 15360,
                    }
                ],
            },
            {"user": "U002", "text": "<@BBOT> deduplicate this"},
            {"user": "BBOT", "text": "Working on it..."},
        ]

    def test_formats_thread_messages(self, messages):
        result = _gather_thread_context(messages, "BBOT")
        assert "[U001] Hey, this CSV has duplicates" in result
        assert "[U002] <@BBOT> deduplicate this" in result
        assert "[Sandstorm] Working on it..." in result

    def test_includes_bot_messages_with_prefix(self, messages):
        result = _gather_thread_context(messages, "BBOT")
        assert "[Sandstorm] Working on it..." in result
        # Bot messages should not use user ID prefix
        assert "[BBOT]" not in result

    def test_includes_file_attachments(self, messages):
        result = _gather_thread_context(messages, "BBOT")
        assert "[attached: data.csv (text/csv, 15KB)]" in result

    def test_empty_messages(self):
        result = _gather_thread_context([], "BBOT")
        assert result == ""


class TestDownloadThreadFiles:
    def test_binary_files_returned_as_bytes(self):
        """Binary files (images, PDFs) are downloaded as bytes in the second dict."""
        client = AsyncMock()
        client.token = "xoxb-test-token"

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.read = AsyncMock(return_value=b"\x89PNG\r\n\x1a\n")

        # session.get() returns an async context manager
        mock_get_ctx = AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(),
        )
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_get_ctx)

        # ClientSession() itself is an async context manager wrapping the loop
        mock_session_ctx = AsyncMock(
            __aenter__=AsyncMock(return_value=mock_session),
            __aexit__=AsyncMock(),
        )

        messages = [
            {
                "user": "U001",
                "files": [
                    {
                        "id": "F001",
                        "name": "photo.png",
                        "mimetype": "image/png",
                        "size": 1000,
                        "url_private": "https://example.com/photo.png",
                    }
                ],
            }
        ]
        with patch("aiohttp.ClientSession", return_value=mock_session_ctx):
            text_files, binary_files = asyncio.run(
                _download_thread_files(client, messages, "BBOT")
            )
        assert text_files == {}
        assert "photo.png" in binary_files
        assert isinstance(binary_files["photo.png"], bytes)

    def test_skips_large_files(self):
        client = AsyncMock()
        messages = [
            {
                "user": "U001",
                "files": [
                    {
                        "id": "F001",
                        "name": "huge.txt",
                        "mimetype": "text/plain",
                        "size": 20 * 1024 * 1024,  # 20MB
                        "url_private": "https://example.com/huge.txt",
                    }
                ],
            }
        ]
        text_files, binary_files = asyncio.run(_download_thread_files(client, messages, "BBOT"))
        assert text_files == {}
        assert binary_files == {}

    def test_downloads_text_files_via_files_info(self):
        client = AsyncMock()
        client.files_info = AsyncMock(return_value={"content": "print('hello')"})
        messages = [
            {
                "user": "U001",
                "files": [
                    {
                        "id": "F001",
                        "name": "script.py",
                        "mimetype": "text/x-python",
                        "size": 500,
                        "url_private": "https://example.com/script.py",
                    }
                ],
            }
        ]
        text_files, binary_files = asyncio.run(_download_thread_files(client, messages, "BBOT"))
        assert text_files == {"script.py": "print('hello')"}
        assert binary_files == {}

    def test_skips_bot_message_files(self):
        client = AsyncMock()
        messages = [
            {
                "user": "BBOT",
                "files": [
                    {
                        "id": "F001",
                        "name": "output.txt",
                        "mimetype": "text/plain",
                        "size": 100,
                        "url_private": "https://example.com/output.txt",
                    }
                ],
            }
        ]
        text_files, binary_files = asyncio.run(_download_thread_files(client, messages, "BBOT"))
        assert text_files == {}
        assert binary_files == {}

    def test_empty_messages(self):
        client = AsyncMock()
        text_files, binary_files = asyncio.run(_download_thread_files(client, [], "BBOT"))
        assert text_files == {}
        assert binary_files == {}


class TestStreamToSlack:
    @pytest.fixture
    def mock_streamer(self):
        streamer = AsyncMock()
        streamer.append = AsyncMock()
        streamer.stop = AsyncMock()
        return streamer

    @pytest.fixture
    def mock_client(self):
        return AsyncMock()

    def _make_async_generator(self, events: list[str]):
        """Create an async generator from a list of JSON strings."""

        async def gen(request, request_id="", **kwargs):
            for event in events:
                yield event

        return gen

    def test_assistant_text_streams_to_slack(self, mock_streamer, mock_client, tmp_path):
        events = [
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": "Hello world"}]},
                }
            ),
            json.dumps(
                {
                    "type": "result",
                    "subtype": "end_turn",
                    "num_turns": 1,
                    "total_cost_usd": 0.01,
                    "model": "sonnet",
                }
            ),
        ]

        gen = self._make_async_generator(events)
        request = _build_query_request("test prompt")

        with (
            patch("sandstorm.slack.run_agent_in_sandbox", gen),
            patch("sandstorm.slack.run_store", RunStore(path=tmp_path / "runs.jsonl")),
        ):
            result = asyncio.run(
                _stream_to_slack(request, "run1", mock_streamer, mock_client, "C001", "1234.5678")
            )

        assert mock_streamer.append.called
        assert mock_streamer.stop.called
        assert result["model"] == "sonnet"
        assert result["cost_usd"] == 0.01
        assert result["num_turns"] == 1

    def test_tool_use_updates_status(self, mock_streamer, mock_client, tmp_path):
        events = [
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "tool_use", "name": "Bash"}]},
                }
            ),
            json.dumps({"type": "result", "subtype": "end_turn", "num_turns": 1}),
        ]

        gen = self._make_async_generator(events)
        request = _build_query_request("test")
        set_status = AsyncMock()

        with (
            patch("sandstorm.slack.run_agent_in_sandbox", gen),
            patch("sandstorm.slack.run_store", RunStore(path=tmp_path / "runs.jsonl")),
        ):
            asyncio.run(
                _stream_to_slack(
                    request,
                    "run2",
                    mock_streamer,
                    mock_client,
                    "C001",
                    "1234.5678",
                    set_status=set_status,
                )
            )

        set_status.assert_any_call("Using Bash...")

    def test_error_event_records_failure(self, mock_streamer, mock_client, tmp_path):
        events = [
            json.dumps({"type": "error", "error": "Sandbox timeout"}),
        ]

        gen = self._make_async_generator(events)
        request = _build_query_request("test")

        with (
            patch("sandstorm.slack.run_agent_in_sandbox", gen),
            patch("sandstorm.slack.run_store", RunStore(path=tmp_path / "runs.jsonl")),
        ):
            result = asyncio.run(
                _stream_to_slack(request, "run3", mock_streamer, mock_client, "C001", "1234.5678")
            )

        assert result["error"] == "Sandbox timeout"

    def test_system_init_sets_model(self, mock_streamer, mock_client, tmp_path):
        events = [
            json.dumps(
                {
                    "type": "system",
                    "subtype": "init",
                    "model": "claude-sonnet-4-20250514",
                }
            ),
            json.dumps({"type": "result", "subtype": "end_turn", "num_turns": 1}),
        ]

        gen = self._make_async_generator(events)
        request = _build_query_request("test")
        set_status = AsyncMock()

        with (
            patch("sandstorm.slack.run_agent_in_sandbox", gen),
            patch("sandstorm.slack.run_store", RunStore(path=tmp_path / "runs.jsonl")),
        ):
            result = asyncio.run(
                _stream_to_slack(
                    request,
                    "run4",
                    mock_streamer,
                    mock_client,
                    "C001",
                    "1234.5678",
                    set_status=set_status,
                )
            )

        set_status.assert_any_call("Running agent on claude-sonnet-4-20250514...")
        assert result["model"] == "claude-sonnet-4-20250514"


class TestSetFeedback:
    def test_set_feedback_stores_values(self, tmp_path):
        store = RunStore(path=tmp_path / "runs.jsonl")
        store.create(id="r1", prompt="test", model="sonnet")
        store.complete(id="r1", cost_usd=0.01)
        store.set_feedback("r1", "positive", "U123")

        run = store._index["r1"]
        assert run.feedback == "positive"
        assert run.feedback_user == "U123"

    def test_set_feedback_persists_to_file(self, tmp_path):
        path = tmp_path / "runs.jsonl"
        store = RunStore(path=path)
        store.create(id="r1", prompt="test", model="sonnet")
        store.complete(id="r1")
        store.set_feedback("r1", "negative", "U456")

        lines = path.read_text().strip().split("\n")
        # complete + set_feedback = 2 lines
        assert len(lines) == 2
        last = json.loads(lines[-1])
        assert last["feedback"] == "negative"
        assert last["feedback_user"] == "U456"

    def test_set_feedback_unknown_id_is_noop(self, tmp_path):
        store = RunStore(path=tmp_path / "runs.jsonl")
        store.set_feedback("nonexistent", "positive", "U123")  # should not raise

    def test_feedback_fields_default_to_none(self, tmp_path):
        store = RunStore(path=tmp_path / "runs.jsonl")
        run = store.create(id="r1", prompt="test", model=None)
        assert run.feedback is None
        assert run.feedback_user is None

    def test_feedback_survives_reload(self, tmp_path):
        """Feedback must persist across server restarts (last-write-wins)."""
        path = tmp_path / "runs.jsonl"
        store = RunStore(path=path)
        store.create(id="r1", prompt="test", model="sonnet")
        store.complete(id="r1", cost_usd=0.01)
        store.set_feedback("r1", "positive", "U123")

        # Reload from file (simulates server restart)
        store2 = RunStore(path=path)
        run = store2._index["r1"]
        assert run.feedback == "positive"
        assert run.feedback_user == "U123"
        assert run.cost_usd == 0.01


class TestStreamToSlackSandboxParams:
    """Verify that _stream_to_slack passes sandbox params to run_agent_in_sandbox."""

    @pytest.fixture
    def mock_streamer(self):
        streamer = AsyncMock()
        streamer.append = AsyncMock()
        streamer.stop = AsyncMock()
        return streamer

    def test_keep_alive_passed_through(self, mock_streamer, tmp_path):
        events = [json.dumps({"type": "result", "subtype": "end_turn", "num_turns": 1})]
        captured_kwargs = {}

        async def gen(request, request_id="", **kwargs):
            captured_kwargs.update(kwargs)
            for event in events:
                yield event

        request = _build_query_request("test")
        with (
            patch("sandstorm.slack.run_agent_in_sandbox", gen),
            patch("sandstorm.slack.run_store", RunStore(path=tmp_path / "runs.jsonl")),
        ):
            asyncio.run(
                _stream_to_slack(
                    request,
                    "run1",
                    mock_streamer,
                    AsyncMock(),
                    "C001",
                    "1234.5678",
                    keep_alive=True,
                )
            )

        assert captured_kwargs["keep_alive"] is True

    def test_sandbox_id_passed_through(self, mock_streamer, tmp_path):
        events = [json.dumps({"type": "result", "subtype": "end_turn", "num_turns": 1})]
        captured_kwargs = {}

        async def gen(request, request_id="", **kwargs):
            captured_kwargs.update(kwargs)
            for event in events:
                yield event

        request = _build_query_request("test")
        with (
            patch("sandstorm.slack.run_agent_in_sandbox", gen),
            patch("sandstorm.slack.run_store", RunStore(path=tmp_path / "runs.jsonl")),
        ):
            asyncio.run(
                _stream_to_slack(
                    request,
                    "run1",
                    mock_streamer,
                    AsyncMock(),
                    "C001",
                    "1234.5678",
                    sandbox_id="sbx-existing-123",
                )
            )

        assert captured_kwargs["sandbox_id"] == "sbx-existing-123"

    def test_sandbox_id_out_passed_through(self, mock_streamer, tmp_path):
        events = [json.dumps({"type": "result", "subtype": "end_turn", "num_turns": 1})]

        async def gen(request, request_id="", **kwargs):
            # Simulate sandbox creation populating the out param
            if kwargs.get("sandbox_id_out") is not None:
                kwargs["sandbox_id_out"].append("sbx-new-456")
            for event in events:
                yield event

        request = _build_query_request("test")
        sandbox_id_out: list[str] = []
        with (
            patch("sandstorm.slack.run_agent_in_sandbox", gen),
            patch("sandstorm.slack.run_store", RunStore(path=tmp_path / "runs.jsonl")),
        ):
            asyncio.run(
                _stream_to_slack(
                    request,
                    "run1",
                    mock_streamer,
                    AsyncMock(),
                    "C001",
                    "1234.5678",
                    sandbox_id_out=sandbox_id_out,
                )
            )

        assert sandbox_id_out == ["sbx-new-456"]

    def test_binary_files_passed_through(self, mock_streamer, tmp_path):
        events = [json.dumps({"type": "result", "subtype": "end_turn", "num_turns": 1})]
        captured_kwargs = {}

        async def gen(request, request_id="", **kwargs):
            captured_kwargs.update(kwargs)
            for event in events:
                yield event

        request = _build_query_request("test")
        binary = {"photo.png": b"\x89PNG\r\n"}
        with (
            patch("sandstorm.slack.run_agent_in_sandbox", gen),
            patch("sandstorm.slack.run_store", RunStore(path=tmp_path / "runs.jsonl")),
        ):
            asyncio.run(
                _stream_to_slack(
                    request,
                    "run1",
                    mock_streamer,
                    AsyncMock(),
                    "C001",
                    "1234.5678",
                    binary_files=binary,
                )
            )

        assert captured_kwargs["binary_files"] == {"photo.png": b"\x89PNG\r\n"}
