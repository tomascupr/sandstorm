"""Tests for the Google Chat events route (gchat_routes.py)."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from sandstorm.main import app

client = TestClient(app)

ENDPOINT = "/gchat/events"


class TestGChatEventsGate:
    def test_returns_503_without_service_account(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_CHAT_SERVICE_ACCOUNT_KEY", raising=False)
        resp = client.post(ENDPOINT, json={"type": "MESSAGE"})
        assert resp.status_code == 503
        assert "not configured" in resp.json()["error"]


class TestGChatEventsAuth:
    def test_returns_401_without_auth_header(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CHAT_SERVICE_ACCOUNT_KEY", "/tmp/fake.json")
        monkeypatch.setenv("GOOGLE_CHAT_PROJECT_NUMBER", "123456")
        with patch("sandstorm.gchat_routes._verify_google_chat_jwt", return_value=False):
            resp = client.post(ENDPOINT, json={"type": "MESSAGE"})
        assert resp.status_code == 401

    def test_accepts_valid_jwt(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CHAT_SERVICE_ACCOUNT_KEY", "/tmp/fake.json")
        monkeypatch.setenv("GOOGLE_CHAT_PROJECT_NUMBER", "123456")
        with patch("sandstorm.gchat_routes._verify_google_chat_jwt", return_value=True):
            resp = client.post(
                ENDPOINT,
                json={"type": "ADDED_TO_SPACE", "space": {"name": "spaces/test"}},
                headers={"Authorization": "Bearer valid-token"},
            )
        assert resp.status_code == 200


class TestGChatAddedToSpace:
    def test_returns_welcome_message(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CHAT_SERVICE_ACCOUNT_KEY", "/tmp/fake.json")
        monkeypatch.setenv("GOOGLE_CHAT_PROJECT_NUMBER", "123456")
        with patch("sandstorm.gchat_routes._verify_google_chat_jwt", return_value=True):
            resp = client.post(
                ENDPOINT,
                json={"type": "ADDED_TO_SPACE", "space": {"name": "spaces/test"}},
                headers={"Authorization": "Bearer valid-token"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "text" in body or "cardsV2" in body


class TestGChatSlashCommands:
    """Test slash command routing through the HTTP endpoint."""

    def _post_slash(self, monkeypatch, command_id, text=""):
        monkeypatch.setenv("GOOGLE_CHAT_SERVICE_ACCOUNT_KEY", "/tmp/fake.json")
        monkeypatch.setenv("GOOGLE_CHAT_PROJECT_NUMBER", "123456")
        body = {
            "type": "MESSAGE",
            "message": {
                "slashCommand": {"commandId": str(command_id)},
                "argumentText": text,
            },
            "user": {"name": "users/123"},
            "space": {"name": "spaces/abc"},
        }
        with patch("sandstorm.gchat_routes._verify_google_chat_jwt", return_value=True):
            return client.post(
                ENDPOINT,
                json=body,
                headers={"Authorization": "Bearer valid"},
            )

    def test_remember_command(self, monkeypatch, tmp_path):
        from sandstorm.memory import MemoryStore
        store = MemoryStore(path=tmp_path / "mem.jsonl")
        with patch("sandstorm.gchat.memory_store", store):
            resp = self._post_slash(monkeypatch, 1, "likes coffee")
        assert resp.status_code == 200
        assert "Remembered" in resp.json()["text"]

    def test_memories_command(self, monkeypatch, tmp_path):
        from sandstorm.memory import MemoryStore
        store = MemoryStore(path=tmp_path / "mem.jsonl")
        with patch("sandstorm.gchat.memory_store", store):
            resp = self._post_slash(monkeypatch, 5)
        assert resp.status_code == 200
        assert "No memories" in resp.json()["text"]

    def test_forget_command(self, monkeypatch, tmp_path):
        from sandstorm.memory import MemoryStore
        store = MemoryStore(path=tmp_path / "mem.jsonl")
        with patch("sandstorm.gchat.memory_store", store):
            resp = self._post_slash(monkeypatch, 4, "nonexistent")
        assert resp.status_code == 200
        assert "No memory matched" in resp.json()["text"]

    def test_cancel_no_active_run(self, monkeypatch, tmp_path):
        from sandstorm.store import RunStore
        store = RunStore(path=tmp_path / "runs.jsonl")
        with patch("sandstorm.gchat.run_store", store):
            resp = self._post_slash(monkeypatch, 7)
        assert resp.status_code == 200
        assert "no in-flight run" in resp.json()["text"].lower()

    def test_unknown_command(self, monkeypatch):
        resp = self._post_slash(monkeypatch, 99)
        assert resp.status_code == 200
        assert "Unknown" in resp.json()["text"]


class TestGChatCardClicked:
    """Test CARD_CLICKED event handling."""

    def _post_card_click(self, monkeypatch, method_name, params):
        monkeypatch.setenv("GOOGLE_CHAT_SERVICE_ACCOUNT_KEY", "/tmp/fake.json")
        monkeypatch.setenv("GOOGLE_CHAT_PROJECT_NUMBER", "123456")
        body = {
            "type": "CARD_CLICKED",
            "action": {
                "actionMethodName": method_name,
                "parameters": [{"key": k, "value": v} for k, v in params.items()],
            },
            "user": {"name": "users/123"},
            "space": {"name": "spaces/abc"},
        }
        with patch("sandstorm.gchat_routes._verify_google_chat_jwt", return_value=True):
            return client.post(
                ENDPOINT,
                json=body,
                headers={"Authorization": "Bearer valid"},
            )

    def test_feedback_positive(self, monkeypatch, tmp_path):
        from sandstorm.store import RunStore
        store = RunStore(path=tmp_path / "runs.jsonl")
        with patch("sandstorm.store.run_store", store):
            resp = self._post_card_click(
                monkeypatch, "sandstorm_feedback",
                {"run_id": "abc123", "sentiment": "positive"},
            )
        assert resp.status_code == 200
        assert "Feedback" in resp.json().get("text", "")

    def test_feedback_negative(self, monkeypatch, tmp_path):
        from sandstorm.store import RunStore
        store = RunStore(path=tmp_path / "runs.jsonl")
        with patch("sandstorm.store.run_store", store):
            resp = self._post_card_click(
                monkeypatch, "sandstorm_feedback",
                {"run_id": "abc123", "sentiment": "negative"},
            )
        assert resp.status_code == 200
        assert "Feedback" in resp.json().get("text", "")

    def test_cancel_run(self, monkeypatch):
        with patch("sandstorm.cancellation.request_cancellation", return_value=True) as mock_cancel:
            resp = self._post_card_click(
                monkeypatch, "sandstorm_cancel_run",
                {"run_id": "run123"},
            )
        assert resp.status_code == 200
        assert "Cancelled" in resp.json().get("text", "") or "Cancel" in resp.json().get("text", "")

    def test_forget_memory(self, monkeypatch, tmp_path):
        from sandstorm.memory import MemoryStore
        store = MemoryStore(path=tmp_path / "mem.jsonl")
        with patch("sandstorm.memory.memory_store", store):
            resp = self._post_card_click(
                monkeypatch, "sandstorm_forget_memory",
                {"memory_id": "mem123"},
            )
        assert resp.status_code == 200


class TestGChatAppHome:
    def test_returns_cards_v2(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CHAT_SERVICE_ACCOUNT_KEY", "/tmp/fake.json")
        monkeypatch.setenv("GOOGLE_CHAT_PROJECT_NUMBER", "123456")
        body = {
            "type": "APP_HOME",
            "user": {"name": "users/123"},
            "space": {"name": "spaces/abc"},
        }
        with patch("sandstorm.gchat_routes._verify_google_chat_jwt", return_value=True):
            resp = client.post(
                ENDPOINT,
                json=body,
                headers={"Authorization": "Bearer valid"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "cardsV2" in data


class TestGChatErrorHandling:
    def test_empty_body_returns_empty(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CHAT_SERVICE_ACCOUNT_KEY", "/tmp/fake.json")
        monkeypatch.setenv("GOOGLE_CHAT_PROJECT_NUMBER", "123456")
        with patch("sandstorm.gchat_routes._verify_google_chat_jwt", return_value=True):
            resp = client.post(
                ENDPOINT,
                json={},
                headers={"Authorization": "Bearer valid"},
            )
        assert resp.status_code == 200

    def test_unknown_event_type(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CHAT_SERVICE_ACCOUNT_KEY", "/tmp/fake.json")
        monkeypatch.setenv("GOOGLE_CHAT_PROJECT_NUMBER", "123456")
        with patch("sandstorm.gchat_routes._verify_google_chat_jwt", return_value=True):
            resp = client.post(
                ENDPOINT,
                json={"type": "SOME_FUTURE_EVENT"},
                headers={"Authorization": "Bearer valid"},
            )
        assert resp.status_code == 200
