"""Tests for the `ds doctor` preflight."""

import asyncio
from unittest.mock import patch

from click.testing import CliRunner

from sandstorm.cli import cli
from sandstorm.doctor import run_checks


def _clear_provider_env(monkeypatch):
    for var in (
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_FOUNDRY",
        "ANTHROPIC_BASE_URL",
        "E2B_API_KEY",
        "SLACK_BOT_TOKEN",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
    ):
        monkeypatch.delenv(var, raising=False)


class TestRunChecks:
    def test_flags_missing_provider_credentials(self, monkeypatch):
        _clear_provider_env(monkeypatch)
        results = asyncio.run(run_checks())
        provider_check = next(c for c in results if c.name == "Provider credentials")
        assert provider_check.passed is False
        assert "ANTHROPIC_API_KEY" in provider_check.hint

        e2b_check = next(c for c in results if c.name == "E2B credentials")
        assert e2b_check.passed is False
        assert "E2B_API_KEY" in e2b_check.hint

    def test_passes_with_custom_base_url_and_valid_e2b(self, monkeypatch):
        _clear_provider_env(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://openrouter.example")
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-openrouter-x")
        monkeypatch.setenv("E2B_API_KEY", "e2b_fake_key")

        async def _fake_e2b(api_key):
            return (True, "OK (0 sandboxes visible)")

        with patch("sandstorm.doctor._probe_e2b", side_effect=_fake_e2b):
            results = asyncio.run(run_checks())

        provider_check = next(c for c in results if c.name == "Provider credentials")
        assert provider_check.passed is True
        assert "custom base URL" in provider_check.detail

        e2b_check = next(c for c in results if c.name == "E2B credentials")
        assert e2b_check.passed is True


class TestDoctorCli:
    def test_doctor_exits_nonzero_when_checks_fail(self, monkeypatch):
        monkeypatch.setattr("sandstorm.cli.load_dotenv", lambda: None)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_USE_VERTEX", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_USE_BEDROCK", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_USE_FOUNDRY", raising=False)
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
        monkeypatch.delenv("E2B_API_KEY", raising=False)
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)

        runner = CliRunner()
        result = runner.invoke(cli, ["doctor"])
        assert result.exit_code == 1
        assert "Provider credentials" in result.output
        assert "E2B_API_KEY" in result.output
