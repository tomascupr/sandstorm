"""Tests for the Google Chat adapter."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sandstorm.gchat import GChatStreamer


@pytest.fixture(autouse=True)
def _set_required_env_vars(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.setenv("E2B_API_KEY", "e2b-test-key")


class TestGChatStreamer:
    def test_append_buffers_text(self):
        service = MagicMock()
        streamer = GChatStreamer(service, "spaces/test", "spaces/test/messages/123", "thread-1")
        asyncio.run(streamer.append(markdown_text="Hello "))
        asyncio.run(streamer.append(markdown_text="world"))
        assert streamer._buffer == "Hello world"

    def test_flush_on_interval(self):
        service = MagicMock()
        execute_mock = MagicMock()
        service.spaces().messages().update().execute = execute_mock
        streamer = GChatStreamer(service, "spaces/test", "spaces/test/messages/123", "thread-1")
        streamer._last_update = time.monotonic() - 3.0  # pretend 3s ago

        asyncio.run(streamer.append(markdown_text="Hello"))
        # Should have flushed because >2s since last update
        assert streamer._accumulated == "Hello"
        assert streamer._buffer == ""

    def test_stop_flushes_remaining(self):
        service = MagicMock()
        execute_mock = MagicMock()
        service.spaces().messages().update().execute = execute_mock
        streamer = GChatStreamer(service, "spaces/test", "spaces/test/messages/123", "thread-1")

        asyncio.run(streamer.append(markdown_text="Final text"))
        asyncio.run(streamer.stop())
        assert streamer._accumulated == "Final text"
        assert streamer._buffer == ""

    def test_stop_with_cards(self):
        service = MagicMock()
        execute_mock = MagicMock()
        service.spaces().messages().update().execute = execute_mock
        streamer = GChatStreamer(service, "spaces/test", "spaces/test/messages/123", "thread-1")

        asyncio.run(streamer.append(markdown_text="Done"))
        cards = [{"cardId": "meta", "card": {"sections": []}}]
        asyncio.run(streamer.stop(blocks=cards))
        assert streamer._accumulated == "Done"
