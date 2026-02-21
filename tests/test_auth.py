import pytest
from unittest.mock import patch, AsyncMock


class TestStartupValidation:
    """Test that API key validation works correctly at startup."""

    def test_startup_fails_if_key_too_short(self, monkeypatch):
        """Startup must fail if SANDSTORM_API_KEY is shorter than 32 characters."""
        monkeypatch.setenv("SANDSTORM_API_KEY", "short-key")

        from sandstorm.auth import load_api_keys

        with pytest.raises(ValueError, match="must be at least 32 characters long"):
            load_api_keys()

    def test_startup_succeeds_with_valid_key(self, monkeypatch):
        """Startup succeeds with valid 32+ character key."""
        valid_key = "test-token-12345678901234567890abcdef"
        monkeypatch.setenv("SANDSTORM_API_KEY", valid_key)

        from sandstorm.auth import load_api_keys, is_auth_enabled

        load_api_keys()
        assert is_auth_enabled()

    def test_startup_without_key_disables_auth(self, monkeypatch):
        """When SANDSTORM_API_KEY is not set, auth is disabled."""
        monkeypatch.delenv("SANDSTORM_API_KEY", raising=False)

        from sandstorm.auth import load_api_keys, is_auth_enabled

        load_api_keys()
        assert not is_auth_enabled()


class TestAuthentication:
    """Test authentication success and failure scenarios."""

    def test_valid_token_succeeds(self, client, valid_token, mock_sandbox):
        """Valid Bearer token allows request to proceed."""
        response = client.post(
            "/query",
            headers={"Authorization": f"Bearer {valid_token}"},
            json={"prompt": "test prompt"},
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

    def test_missing_token_returns_401_with_www_authenticate(self, client, mock_sandbox):
        """Request without Authorization header returns 401 with WWW-Authenticate header."""
        response = client.post(
            "/query",
            json={"prompt": "test prompt"},
        )

        assert response.status_code == 401
        assert "WWW-Authenticate" in response.headers
        assert response.headers["WWW-Authenticate"] == "Bearer"
        assert response.json()["detail"] == "Not authenticated"

    def test_invalid_token_returns_401(self, client, mock_sandbox):
        """Request with invalid token returns 401."""
        response = client.post(
            "/query",
            headers={"Authorization": "Bearer invalid-token-xyz"},
            json={"prompt": "test prompt"},
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid authentication credentials"

    def test_token_rotation_with_previous_key(
        self, client_with_rotation, test_env_with_rotation, mock_sandbox
    ):
        """Both current and previous tokens are accepted during rotation."""
        current_token, previous_token = test_env_with_rotation

        response_current = client_with_rotation.post(
            "/query",
            headers={"Authorization": f"Bearer {current_token}"},
            json={"prompt": "test with current"},
        )
        assert response_current.status_code == 200

        response_previous = client_with_rotation.post(
            "/query",
            headers={"Authorization": f"Bearer {previous_token}"},
            json={"prompt": "test with previous"},
        )
        assert response_previous.status_code == 200

    def test_malformed_auth_header(self, client, mock_sandbox):
        """Malformed Authorization header (not Bearer scheme) returns 401."""
        response = client.post(
            "/query",
            headers={"Authorization": "token-without-bearer-prefix"},
            json={"prompt": "test"},
        )
        assert response.status_code == 401

        response = client.post(
            "/query",
            headers={"Authorization": "Basic dGVzdDp0ZXN0"},
            json={"prompt": "test"},
        )
        assert response.status_code == 401


class TestOptionalAuth:
    """Auth is optional -- disabled when SANDSTORM_API_KEY is not set."""

    def test_no_auth_required_when_key_not_set(self, client_no_auth, mock_sandbox):
        """Without SANDSTORM_API_KEY, requests proceed without auth."""
        response = client_no_auth.post(
            "/query",
            json={"prompt": "test prompt"},
        )
        assert response.status_code == 200

    def test_health_works_without_auth(self, client_no_auth):
        """Health endpoint works without auth configured."""
        response = client_no_auth.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestSecurityGuarantees:
    """Critical security tests - unauthorized requests must never execute code."""

    def test_unauthorized_never_executes_sandbox(self, client):
        """Unauthorized requests must never reach sandbox execution."""
        with patch("sandstorm.sandbox.run_agent_in_sandbox") as mock_sandbox:
            mock_sandbox.return_value = AsyncMock()

            response = client.post("/query", json={"prompt": "test"})
            assert response.status_code == 401
            mock_sandbox.assert_not_called()

            response = client.post(
                "/query",
                headers={"Authorization": "Bearer invalid-token"},
                json={"prompt": "test"},
            )
            assert response.status_code == 401
            mock_sandbox.assert_not_called()


class TestHealthEndpoint:
    """Health endpoint should not require authentication."""

    def test_health_endpoint_no_auth_required(self, client):
        """Health endpoint must be accessible without authentication."""
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestEdgeCases:
    """Test edge cases and unusual input scenarios."""

    def test_empty_bearer_token(self, client):
        """Empty Bearer token returns 401."""
        response = client.post(
            "/query",
            headers={"Authorization": "Bearer "},
            json={"prompt": "test"},
        )
        assert response.status_code == 401

    def test_case_sensitive_token_validation(self, client, valid_token):
        """Token comparison must be case-sensitive."""
        uppercase_token = valid_token.upper()

        response = client.post(
            "/query",
            headers={"Authorization": f"Bearer {uppercase_token}"},
            json={"prompt": "test"},
        )
        assert response.status_code == 401

    def test_previous_key_too_short_is_ignored(self, monkeypatch, valid_token):
        """SANDSTORM_API_KEY_PREVIOUS shorter than 32 chars is silently ignored."""
        monkeypatch.setenv("SANDSTORM_API_KEY", valid_token)
        monkeypatch.setenv("SANDSTORM_API_KEY_PREVIOUS", "short")

        from sandstorm.auth import load_api_keys

        load_api_keys()
        from sandstorm import auth

        assert len(auth._valid_keys) == 1


class TestLogging:
    """Test security logging behavior."""

    def test_failed_auth_logs_ip_address(self, client, caplog):
        """Failed authentication attempts should log IP address."""
        import logging

        caplog.set_level(logging.WARNING)

        response = client.post(
            "/query",
            headers={"Authorization": "Bearer invalid-token"},
            json={"prompt": "test"},
        )

        assert response.status_code == 401
        log_messages = [record.message for record in caplog.records]
        assert any("testclient" in msg for msg in log_messages)

    def test_failed_auth_redacts_full_token(self, client, caplog):
        """Failed authentication should not log full token."""
        import logging

        caplog.set_level(logging.WARNING)

        full_token = "secret-token-12345678901234567890"

        response = client.post(
            "/query",
            headers={"Authorization": f"Bearer {full_token}"},
            json={"prompt": "test"},
        )

        assert response.status_code == 401
        log_text = " ".join([record.message for record in caplog.records])
        assert full_token not in log_text
