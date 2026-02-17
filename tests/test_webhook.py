"""Tests for the E2B webhook endpoint and auto-registration helpers."""

import hashlib
import hmac
import json

from fastapi.testclient import TestClient

import sandstorm.main as main_mod
from sandstorm.main import app

client = TestClient(app)


class TestWebhookEndpoint:
    def test_webhook_valid_payload(self):
        payload = {"type": "sandbox.lifecycle.created", "sandboxId": "abc"}
        response = client.post("/webhooks/e2b", json=payload)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_webhook_invalid_json(self):
        response = client.post(
            "/webhooks/e2b",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400
        assert "invalid JSON" in response.json()["error"]

    def test_webhook_invalid_signature(self, monkeypatch):
        monkeypatch.setattr(main_mod, "_WEBHOOK_SECRET", "testsecret")
        payload = {"type": "sandbox.lifecycle.created", "sandboxId": "abc"}
        response = client.post(
            "/webhooks/e2b",
            json=payload,
            headers={"e2b-signature": "sha256=bad"},
        )
        assert response.status_code == 401
        assert "invalid signature" in response.json()["error"]

    def test_webhook_valid_signature(self, monkeypatch):
        secret = "testsecret"
        monkeypatch.setattr(main_mod, "_WEBHOOK_SECRET", secret)
        body = json.dumps({"type": "sandbox.lifecycle.created", "sandboxId": "abc"})
        sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        response = client.post(
            "/webhooks/e2b",
            content=body.encode(),
            headers={
                "Content-Type": "application/json",
                "e2b-signature": f"sha256={sig}",
            },
        )
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestAutoRegisterWebhook:
    def test_auto_register_skipped_without_config(self, monkeypatch):
        monkeypatch.setattr(main_mod, "load_sandstorm_config", lambda: None)
        result = main_mod._auto_register_webhook()
        assert result is None

    def test_auto_register_skipped_without_api_key(self, monkeypatch):
        monkeypatch.setattr(
            main_mod,
            "load_sandstorm_config",
            lambda: {"webhook_url": "http://localhost:8000"},
        )
        monkeypatch.delenv("E2B_API_KEY", raising=False)
        result = main_mod._auto_register_webhook()
        assert result is None
