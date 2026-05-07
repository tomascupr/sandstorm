"""Tests for the Google Chat adapter."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sandstorm.gchat import (
    GChatStreamer,
    build_metadata_cards,
    dispatch_slash_command,
    parse_event_type,
)


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


class TestParseEventType:
    def test_added_to_space(self):
        assert parse_event_type({"type": "ADDED_TO_SPACE"}) == "added_to_space"

    def test_message_with_slash_command(self):
        body = {"type": "MESSAGE", "message": {"slashCommand": {"commandId": "1"}}}
        assert parse_event_type(body) == "slash_command"

    def test_message_in_dm(self):
        body = {"type": "MESSAGE", "space": {"type": "DM"}, "message": {"text": "hi"}}
        assert parse_event_type(body) == "dm_message"

    def test_message_with_mention(self):
        body = {"type": "MESSAGE", "space": {"type": "ROOM"}, "message": {"text": "@bot help"}}
        assert parse_event_type(body) == "mention"

    def test_card_clicked(self):
        body = {"type": "CARD_CLICKED", "action": {"actionMethodName": "feedback"}}
        assert parse_event_type(body) == "card_clicked"

    def test_app_home(self):
        assert parse_event_type({"type": "APP_HOME"}) == "app_home"

    def test_reaction_added(self):
        assert parse_event_type({"type": "REACTION_ADDED"}) == "reaction_added"

    def test_unknown(self):
        assert parse_event_type({"type": "SOMETHING_ELSE"}) == "unknown"


class TestBuildMetadataCards:
    def test_returns_cards_v2_format(self):
        cards = build_metadata_cards("run1", "sonnet", 0.01, 3, 12.5)
        assert isinstance(cards, list)
        assert len(cards) > 0
        assert "cardId" in cards[0]
        assert "card" in cards[0]

    def test_includes_feedback_buttons(self):
        cards = build_metadata_cards("run1", "sonnet", 0.01, 3, 12.5)
        sections = cards[0]["card"]["sections"]
        buttons_found = False
        for section in sections:
            for widget in section.get("widgets", []):
                if "buttonList" in widget:
                    buttons_found = True
                    buttons = widget["buttonList"]["buttons"]
                    assert len(buttons) == 2
        assert buttons_found

    def test_includes_metadata_text(self):
        cards = build_metadata_cards("run1", "sonnet", 0.01, 3, 12.5)
        sections = cards[0]["card"]["sections"]
        text_found = False
        for section in sections:
            for widget in section.get("widgets", []):
                if "textParagraph" in widget:
                    text = widget["textParagraph"]["text"]
                    assert "sonnet" in text
                    assert "0.0100" in text
                    text_found = True
        assert text_found


class TestDispatchSlashCommand:
    def test_remember_command(self, tmp_path):
        from sandstorm.memory import MemoryStore

        store = MemoryStore(path=tmp_path / "mem.jsonl")
        body = {
            "message": {"slashCommand": {"commandId": "1"}, "argumentText": "likes coffee"},
            "user": {"name": "users/123"},
            "space": {"name": "spaces/abc"},
        }
        with patch("sandstorm.gchat.memory_store", store):
            result = dispatch_slash_command(body, team_id="T1", user_id="U1")
        assert "Remembered" in result["text"]

    def test_memories_command_empty(self, tmp_path):
        from sandstorm.memory import MemoryStore

        store = MemoryStore(path=tmp_path / "mem.jsonl")
        body = {
            "message": {"slashCommand": {"commandId": "5"}, "argumentText": ""},
            "user": {"name": "users/123"},
            "space": {"name": "spaces/abc"},
        }
        with patch("sandstorm.gchat.memory_store", store):
            result = dispatch_slash_command(body, team_id="T1", user_id="U1")
        assert "No memories" in result["text"]

    def test_forget_command_no_match(self, tmp_path):
        from sandstorm.memory import MemoryStore

        store = MemoryStore(path=tmp_path / "mem.jsonl")
        body = {
            "message": {"slashCommand": {"commandId": "4"}, "argumentText": "nonexistent"},
            "user": {"name": "users/123"},
            "space": {"name": "spaces/abc"},
        }
        with patch("sandstorm.gchat.memory_store", store):
            result = dispatch_slash_command(body, team_id="T1", user_id="U1")
        assert "No memory matched" in result["text"]

    def test_unknown_command(self):
        body = {
            "message": {"slashCommand": {"commandId": "99"}, "argumentText": ""},
            "user": {"name": "users/123"},
            "space": {"name": "spaces/abc"},
        }
        result = dispatch_slash_command(body, team_id="T1", user_id="U1")
        assert "Unknown" in result["text"]


from sandstorm.gchat_app_home import build_home_card


class TestGChatAppHome:
    def test_builds_valid_card(self):
        card = build_home_card(team_id="T1", user_id="U1")
        assert "cardId" in card
        assert "card" in card

    def test_includes_header(self):
        card = build_home_card(team_id="T1", user_id="U1")
        header = card["card"].get("header", {})
        assert "Sandstorm" in header.get("title", "")

    def test_has_sections(self):
        card = build_home_card(team_id="T1", user_id="U1")
        sections = card["card"].get("sections", [])
        assert len(sections) >= 1


class TestGChatFileDownload:
    def test_classifies_binary_files(self):
        from sandstorm.platform import BINARY_MIME_PREFIXES
        assert any("image/png".startswith(p) for p in BINARY_MIME_PREFIXES)
        assert not any("text/plain".startswith(p) for p in BINARY_MIME_PREFIXES)


class TestGChatThreadContext:
    def test_fetch_and_format_thread(self):
        from sandstorm.platform import gather_thread_context
        messages = [
            {"user": "users/123", "text": "Help with this"},
            {"user": "BOT_ID", "text": "Working on it..."},
        ]
        result = gather_thread_context(messages, "BOT_ID")
        assert "[users/123] Help with this" in result
        assert "[Sandstorm] Working on it..." in result
