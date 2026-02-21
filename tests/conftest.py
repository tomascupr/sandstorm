import pytest
from unittest.mock import patch

from fastapi.testclient import TestClient


@pytest.fixture
def valid_token():
    """Generate a valid test token (32+ characters)."""
    return "test-token-12345678901234567890abcdef"


@pytest.fixture
def previous_token():
    """Generate a previous token for rotation testing."""
    return "prev-token-12345678901234567890abcdef"


@pytest.fixture
def test_env(monkeypatch, valid_token):
    """Setup test environment with auth enabled."""
    monkeypatch.setenv("SANDSTORM_API_KEY", valid_token)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key-123")
    monkeypatch.setenv("E2B_API_KEY", "e2b_test_key_123")
    monkeypatch.setenv("CORS_ORIGINS", "*")
    return valid_token


@pytest.fixture
def test_env_no_auth(monkeypatch):
    """Setup test environment without auth (local dev mode)."""
    monkeypatch.delenv("SANDSTORM_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key-123")
    monkeypatch.setenv("E2B_API_KEY", "e2b_test_key_123")
    monkeypatch.setenv("CORS_ORIGINS", "*")


@pytest.fixture
def test_env_with_rotation(monkeypatch, valid_token, previous_token):
    """Setup test environment with token rotation support."""
    monkeypatch.setenv("SANDSTORM_API_KEY", valid_token)
    monkeypatch.setenv("SANDSTORM_API_KEY_PREVIOUS", previous_token)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key-123")
    monkeypatch.setenv("E2B_API_KEY", "e2b_test_key_123")
    monkeypatch.setenv("CORS_ORIGINS", "*")
    return valid_token, previous_token


@pytest.fixture
def mock_sandbox():
    """Mock sandbox execution to prevent actual E2B calls."""

    async def _mock_generator(*args, **kwargs):
        yield '{"type": "status", "status": "running"}'
        yield '{"type": "output", "output": "test output"}'
        yield '{"type": "status", "status": "completed"}'

    with patch(
        "sandstorm.sandbox.run_agent_in_sandbox",
        side_effect=_mock_generator,
    ) as mock:
        yield mock


@pytest.fixture
def client(test_env, mock_sandbox):
    """TestClient with auth enabled."""
    from sandstorm.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def client_no_auth(test_env_no_auth, mock_sandbox):
    """TestClient without auth (local dev mode)."""
    from sandstorm.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def client_with_rotation(test_env_with_rotation, mock_sandbox):
    """TestClient with token rotation enabled."""
    from sandstorm.main import app

    with TestClient(app) as test_client:
        yield test_client
