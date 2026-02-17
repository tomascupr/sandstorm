"""Optional OpenTelemetry integration for Sandstorm.

Activated by setting ``SANDSTORM_TELEMETRY=1``.  When the env var is unset or
the OpenTelemetry packages are not installed, every public function in this
module is a safe no-op — zero overhead on the hot path.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


class _NoOpSpan:
    """Minimal stand-in when opentelemetry is not installed."""

    def is_recording(self):
        return False

    def set_attribute(self, key, value):
        pass

    def set_status(self, status, description=None):
        pass

    def record_exception(self, exception):
        pass


class _NoOpTracer:
    """Minimal stand-in when opentelemetry is not installed."""

    @contextmanager
    def start_as_current_span(self, name, **kwargs):
        yield _NoOpSpan()


# ── Module state (set by init()) ────────────────────────────────────────────
_ENABLED = False

_tracer = None  # Real tracer when enabled
_request_counter = None
_request_duration = None
_sandbox_creation_duration = None
_agent_execution_duration = None
_active_sandboxes = None
_error_counter = None
_queue_drop_counter = None
_webhook_event_counter = None


def _is_enabled() -> bool:
    return os.environ.get("SANDSTORM_TELEMETRY", "").strip() == "1"


# ── Initialisation ──────────────────────────────────────────────────────────


def init(app: FastAPI | None = None) -> None:
    """Initialise OpenTelemetry providers and instrument FastAPI.

    All OTel imports live inside this function so the module is safe to import
    even when the ``telemetry`` extra is not installed.
    """
    global _ENABLED, _tracer  # noqa: PLW0603
    global _request_counter, _request_duration  # noqa: PLW0603
    global _sandbox_creation_duration, _agent_execution_duration  # noqa: PLW0603
    global _active_sandboxes, _error_counter, _queue_drop_counter  # noqa: PLW0603
    global _webhook_event_counter  # noqa: PLW0603

    if not _is_enabled():
        return

    try:
        from opentelemetry import metrics, trace  # type: ignore[reportMissingImports]
        from opentelemetry.sdk._logs import (  # type: ignore[reportMissingImports]
            LoggerProvider,
            LoggingHandler,
        )
        from opentelemetry.sdk._logs.export import (
            BatchLogRecordProcessor,  # type: ignore[reportMissingImports]
        )
        from opentelemetry.sdk.metrics import MeterProvider  # type: ignore[reportMissingImports]
        from opentelemetry.sdk.metrics.export import (
            PeriodicExportingMetricReader,  # type: ignore[reportMissingImports]
        )
        from opentelemetry.sdk.resources import Resource  # type: ignore[reportMissingImports]
        from opentelemetry.sdk.trace import TracerProvider  # type: ignore[reportMissingImports]
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,  # type: ignore[reportMissingImports]
        )
    except ImportError:
        logger.warning(
            "SANDSTORM_TELEMETRY=1 but OpenTelemetry packages are not installed. "
            "Install with: uv sync --extra telemetry"
        )
        return

    from . import __version__

    resource = Resource.create(
        {
            "service.name": "sandstorm",
            "service.version": __version__,
        }
    )

    # ── Exporter selection (gRPC default, HTTP/protobuf alt) ────────────
    protocol = os.environ.get("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc")
    if protocol == "http/protobuf":
        from opentelemetry.exporter.otlp.proto.http._log_exporter import (  # type: ignore[reportMissingImports]
            OTLPLogExporter,
        )
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (  # type: ignore[reportMissingImports]
            OTLPMetricExporter,
        )
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[reportMissingImports]
            OTLPSpanExporter,
        )
    else:
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import (  # type: ignore[reportMissingImports]
            OTLPLogExporter,
        )
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (  # type: ignore[reportMissingImports]
            OTLPMetricExporter,
        )
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # type: ignore[reportMissingImports]
            OTLPSpanExporter,
        )

    # ── Traces ──────────────────────────────────────────────────────────
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    # ── Metrics ─────────────────────────────────────────────────────────
    metric_reader = PeriodicExportingMetricReader(OTLPMetricExporter())
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    # ── Logs bridge ─────────────────────────────────────────────────────
    log_provider = LoggerProvider(resource=resource)
    log_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    handler = LoggingHandler(level=logging.NOTSET, logger_provider=log_provider)
    logging.getLogger().addHandler(handler)

    # ── FastAPI auto-instrumentation ────────────────────────────────────
    if app is not None:
        try:
            from opentelemetry.instrumentation.fastapi import (
                FastAPIInstrumentor,  # type: ignore[reportMissingImports]
            )

            FastAPIInstrumentor.instrument_app(app)
        except Exception:
            logger.warning("Failed to instrument FastAPI app", exc_info=True)

    # ── Create metric instruments ───────────────────────────────────────
    meter = metrics.get_meter("sandstorm", __version__)

    _request_counter = meter.create_counter(
        "sandstorm.requests",
        unit="1",
        description="Total query requests",
    )
    _request_duration = meter.create_histogram(
        "sandstorm.request.duration",
        unit="s",
        description="Query request duration",
    )
    _sandbox_creation_duration = meter.create_histogram(
        "sandstorm.sandbox.creation.duration",
        unit="s",
        description="Sandbox creation duration",
    )
    _agent_execution_duration = meter.create_histogram(
        "sandstorm.agent.execution.duration",
        unit="s",
        description="Agent execution duration",
    )
    _active_sandboxes = meter.create_up_down_counter(
        "sandstorm.sandboxes.active",
        unit="1",
        description="Currently active sandboxes",
    )
    _error_counter = meter.create_counter(
        "sandstorm.errors",
        unit="1",
        description="Total errors",
    )
    _queue_drop_counter = meter.create_counter(
        "sandstorm.queue.drops",
        unit="1",
        description="Messages dropped due to full queue",
    )
    _webhook_event_counter = meter.create_counter(
        "sandstorm.webhook.events",
        unit="1",
        description="E2B webhook events received",
    )

    _ENABLED = True
    _tracer = trace.get_tracer("sandstorm", __version__)
    logger.info("OpenTelemetry initialized (protocol=%s)", protocol)


# ── Tracer accessor ─────────────────────────────────────────────────────────


def get_tracer():
    """Return the real tracer when enabled, OTel no-op tracer otherwise."""
    if _tracer is not None:
        return _tracer
    try:
        from opentelemetry import trace  # type: ignore[reportMissingImports]

        return trace.get_tracer("sandstorm")
    except ImportError:
        return _NoOpTracer()


# ── Span error helper ──────────────────────────────────────────────────────


def set_span_error(span: Any, error: BaseException) -> None:
    """Set span status to ERROR.  No-op when telemetry is disabled."""
    if not _ENABLED:
        return
    from opentelemetry.trace import StatusCode  # type: ignore[reportMissingImports]

    span.set_status(StatusCode.ERROR, str(error))
    span.record_exception(error)


# ── Metric helpers (no-ops when disabled) ───────────────────────────────────


def record_request(*, model: str | None = None, status: str = "ok") -> None:
    if _request_counter:
        _request_counter.add(1, {"model": model or "", "status": status})


def record_request_duration(duration: float, *, model: str | None = None) -> None:
    if _request_duration:
        _request_duration.record(duration, {"model": model or ""})


def record_sandbox_creation(duration: float, *, template: str = "") -> None:
    if _sandbox_creation_duration:
        _sandbox_creation_duration.record(duration, {"template": template})


def record_agent_execution(duration: float, *, model: str | None = None) -> None:
    if _agent_execution_duration:
        _agent_execution_duration.record(duration, {"model": model or ""})


def sandbox_started() -> None:
    if _active_sandboxes:
        _active_sandboxes.add(1)


def sandbox_stopped() -> None:
    if _active_sandboxes:
        _active_sandboxes.add(-1)


def record_error(*, error_type: str = "") -> None:
    if _error_counter:
        _error_counter.add(1, {"error_type": error_type})


def record_queue_drop() -> None:
    if _queue_drop_counter:
        _queue_drop_counter.add(1)


def record_webhook_event(*, event_type: str = "") -> None:
    if _webhook_event_counter:
        _webhook_event_counter.add(1, {"sandstorm.webhook.event_type": event_type})
