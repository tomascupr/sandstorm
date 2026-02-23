"""Tests for the Slack events route (slack_routes.py)."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from sandstorm.main import app

client = TestClient(app)

ENDPOINT = "/slack/events"


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


class TestSlackEventsDelegation:
    def test_delegates_to_handler(self, monkeypatch):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
        monkeypatch.setenv("SLACK_SIGNING_SECRET", "test-secret")

        mock_handler = AsyncMock()
        mock_handler.handle = AsyncMock(return_value={"ok": True})

        body = {"type": "event_callback"}

        with patch("sandstorm.slack_routes._get_handler", return_value=mock_handler):
            resp = client.post(ENDPOINT, json=body)

        assert resp.status_code == 200
        mock_handler.handle.assert_called_once()
