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
