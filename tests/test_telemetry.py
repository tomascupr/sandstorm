"""Tests for the telemetry module.

Disabled-state tests always run (no OTel packages required).
Enabled-state tests are skipped when OTel is not installed.
"""

import importlib
import warnings

import pytest

import sandstorm.telemetry as telemetry_mod


@pytest.fixture(autouse=True)
def _reset_telemetry(monkeypatch):
    """Ensure each test starts with a clean telemetry state."""
    monkeypatch.delenv("SANDSTORM_TELEMETRY", raising=False)
    # Reset module-level state
    monkeypatch.setattr(telemetry_mod, "_ENABLED", False)
    monkeypatch.setattr(telemetry_mod, "_tracer", None)
    monkeypatch.setattr(telemetry_mod, "_request_counter", None)
    monkeypatch.setattr(telemetry_mod, "_request_duration", None)
    monkeypatch.setattr(telemetry_mod, "_sandbox_creation_duration", None)
    monkeypatch.setattr(telemetry_mod, "_agent_execution_duration", None)
    monkeypatch.setattr(telemetry_mod, "_active_sandboxes", None)
    monkeypatch.setattr(telemetry_mod, "_error_counter", None)
    monkeypatch.setattr(telemetry_mod, "_queue_drop_counter", None)
    monkeypatch.setattr(telemetry_mod, "_webhook_event_counter", None)


# ── Disabled state (always run) ─────────────────────────────────────────────


class TestDisabledState:
    def test_init_is_noop_when_env_unset(self):
        telemetry_mod.init()
        assert telemetry_mod._ENABLED is False

    def test_init_is_noop_when_env_is_zero(self, monkeypatch):
        monkeypatch.setenv("SANDSTORM_TELEMETRY", "0")
        telemetry_mod.init()
        assert telemetry_mod._ENABLED is False

    def test_init_is_noop_when_env_is_empty(self, monkeypatch):
        monkeypatch.setenv("SANDSTORM_TELEMETRY", "")
        telemetry_mod.init()
        assert telemetry_mod._ENABLED is False

    def test_get_tracer_returns_noop(self):
        tracer = telemetry_mod.get_tracer()
        # The no-op tracer should produce non-recording spans
        with tracer.start_as_current_span("test") as span:
            assert not span.is_recording()

    def test_set_span_error_is_noop(self):
        tracer = telemetry_mod.get_tracer()
        with tracer.start_as_current_span("test") as span:
            # Should not raise
            telemetry_mod.set_span_error(span, RuntimeError("boom"))

    def test_metric_helpers_are_safe_noops(self):
        """All metric functions should be callable without error when disabled."""
        telemetry_mod.record_request(model="test", status="ok")
        telemetry_mod.record_request_duration(1.0, model="test")
        telemetry_mod.record_sandbox_creation(0.5, template="test")
        telemetry_mod.record_agent_execution(10.0, model="test")
        telemetry_mod.sandbox_started()
        telemetry_mod.sandbox_stopped()
        telemetry_mod.record_error(error_type="RuntimeError")
        telemetry_mod.record_queue_drop()
        telemetry_mod.record_webhook_event(event_type="sandbox.started")


class TestMissingPackages:
    def test_warns_when_enabled_but_packages_missing(self, monkeypatch):
        monkeypatch.setenv("SANDSTORM_TELEMETRY", "1")
        # Temporarily hide OTel packages
        real_import = (
            __builtins__.__import__
            if hasattr(__builtins__, "__import__")
            else importlib.__import__
        )

        def mock_import(name, *args, **kwargs):
            if name.startswith("opentelemetry"):
                raise ImportError(f"No module named '{name}'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", mock_import)

        with warnings.catch_warnings(record=True):
            telemetry_mod.init()

        assert telemetry_mod._ENABLED is False


# ── Enabled state (skip when OTel not installed) ────────────────────────────


class TestEnabledState:
    @pytest.fixture(autouse=True)
    def _require_otel(self):
        pytest.importorskip("opentelemetry.sdk")

    @pytest.fixture(autouse=True)
    def _enable_telemetry(self, monkeypatch):
        monkeypatch.setenv("SANDSTORM_TELEMETRY", "1")

    def test_init_sets_enabled(self):
        telemetry_mod.init()
        assert telemetry_mod._ENABLED is True

    def test_init_creates_tracer(self):
        telemetry_mod.init()
        assert telemetry_mod._tracer is not None

    def test_init_creates_metrics(self):
        telemetry_mod.init()
        assert telemetry_mod._request_counter is not None
        assert telemetry_mod._request_duration is not None
        assert telemetry_mod._sandbox_creation_duration is not None
        assert telemetry_mod._agent_execution_duration is not None
        assert telemetry_mod._active_sandboxes is not None
        assert telemetry_mod._error_counter is not None
        assert telemetry_mod._queue_drop_counter is not None
        assert telemetry_mod._webhook_event_counter is not None

    def test_get_tracer_returns_recording(self):
        telemetry_mod.init()
        tracer = telemetry_mod.get_tracer()
        with tracer.start_as_current_span("test") as span:
            assert span.is_recording()

    def test_set_span_error_sets_status(self):
        from opentelemetry.trace import StatusCode

        telemetry_mod.init()
        tracer = telemetry_mod.get_tracer()
        with tracer.start_as_current_span("test") as span:
            telemetry_mod.set_span_error(span, RuntimeError("test error"))
            assert span.status.status_code == StatusCode.ERROR

    def test_metric_helpers_work(self):
        """Metric functions should not raise when enabled."""
        telemetry_mod.init()
        telemetry_mod.record_request(model="claude-sonnet-4-5-20250929", status="ok")
        telemetry_mod.record_request_duration(1.5, model="claude-sonnet-4-5-20250929")
        telemetry_mod.record_sandbox_creation(0.3, template="sandstorm")
        telemetry_mod.record_agent_execution(12.0, model="claude-sonnet-4-5-20250929")
        telemetry_mod.sandbox_started()
        telemetry_mod.sandbox_stopped()
        telemetry_mod.record_error(error_type="SandboxException")
        telemetry_mod.record_queue_drop()
        telemetry_mod.record_webhook_event(event_type="sandbox.started")
