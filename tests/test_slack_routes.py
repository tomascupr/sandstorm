"""Tests for the Slack events route (slack_routes.py)."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from sandstorm.main import app
from sandstorm.slack_routes import _seen_events

client = TestClient(app)

ENDPOINT = "/slack/events"


@pytest.fixture(autouse=True)
def _clear_dedup_cache():
    """Reset the in-memory dedup cache between tests."""
    _seen_events.clear()
    yield
    _seen_events.clear()


class TestSlackEventsGate:
    def test_returns_503_without_bot_token(self, monkeypatch):
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        resp = client.post(ENDPOINT, json={"type": "event_callback"})
        assert resp.status_code == 503
        assert "SLACK_BOT_TOKEN" in resp.json()["error"]


class TestSlackEventsRetry:
    def test_rejects_retries(self, monkeypatch):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
        resp = client.post(
            ENDPOINT,
            json={"type": "event_callback"},
            headers={"X-Slack-Retry-Num": "1"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}


class TestSlackEventsUrlVerification:
    def test_url_verification_challenge(self, monkeypatch):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
        resp = client.post(
            ENDPOINT,
            json={"type": "url_verification", "challenge": "xyz"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"challenge": "xyz"}


class TestSlackEventsDedup:
    def test_dedup_rejects_duplicate_event_id(self, monkeypatch):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
        monkeypatch.setenv("SLACK_SIGNING_SECRET", "test-secret")

        mock_handler = AsyncMock()
        mock_handler.handle = AsyncMock(return_value={"ok": True})

        body = {"type": "event_callback", "event_id": "ev1"}

        with patch("sandstorm.slack_routes._get_handler", return_value=mock_handler):
            # First request — passes through to handler
            resp1 = client.post(ENDPOINT, json=body)
            assert resp1.status_code == 200

            # Second request with same event_id — dedup kicks in
            resp2 = client.post(ENDPOINT, json=body)
            assert resp2.status_code == 200
            assert resp2.json() == {"ok": True, "duplicate": True}


class TestSlackEventsDelegation:
    def test_delegates_to_handler(self, monkeypatch):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
        monkeypatch.setenv("SLACK_SIGNING_SECRET", "test-secret")

        mock_handler = AsyncMock()
        mock_handler.handle = AsyncMock(return_value={"ok": True})

        body = {"type": "event_callback", "event_id": "ev_delegate"}

        with patch("sandstorm.slack_routes._get_handler", return_value=mock_handler):
            resp = client.post(ENDPOINT, json=body)

        assert resp.status_code == 200
        mock_handler.handle.assert_called_once()
