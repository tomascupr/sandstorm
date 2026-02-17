import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import urllib.error
import urllib.request
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from e2b import AuthenticationException, SandboxException

from . import _LOG_DATEFMT, _LOG_FORMAT
from .models import QueryRequest
from .sandbox import load_sandstorm_config, run_agent_in_sandbox
from .telemetry import (
    init as init_telemetry,
    get_tracer,
    set_span_error,
    record_request,
    record_request_duration,
    record_error,
    record_webhook_event,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format=_LOG_FORMAT,
    datefmt=_LOG_DATEFMT,
)
logger = logging.getLogger(__name__)

_E2B_WEBHOOK_API = "https://api.e2b.app/events/webhooks"

_WEBHOOK_SECRET = os.environ.get("SANDSTORM_WEBHOOK_SECRET", "")


def _e2b_webhook_request(
    method: str, path: str, api_key: str, data: dict | None = None
) -> dict | list | None:
    """Make a request to the E2B webhook API."""
    url = f"{_E2B_WEBHOOK_API}{path}"
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"E2B API returned {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to reach E2B API: {exc.reason}") from exc


def _auto_register_webhook() -> str | None:
    """Register an E2B lifecycle webhook from sandstorm.json config.

    Returns the webhook ID on success, None if skipped or on failure.
    """
    global _WEBHOOK_SECRET

    config = load_sandstorm_config()
    webhook_url = config.get("webhook_url") if config else None
    api_key = os.environ.get("E2B_API_KEY", "")

    if not webhook_url or not api_key:
        return None

    # Auto-append /webhooks/e2b if not already present
    if not webhook_url.rstrip("/").endswith("/webhooks/e2b"):
        webhook_url = webhook_url.rstrip("/") + "/webhooks/e2b"

    # Resolve or generate webhook secret
    secret = os.environ.get("SANDSTORM_WEBHOOK_SECRET", "")
    if not secret:
        secret = secrets.token_hex(32)
        _WEBHOOK_SECRET = secret
        logger.info(
            "Auto-generated webhook secret (set SANDSTORM_WEBHOOK_SECRET to persist)"
        )

    payload: dict = {
        "name": "sandstorm-auto",
        "url": webhook_url,
        "enabled": True,
        "signatureSecret": secret,
        "events": [
            "sandbox.lifecycle.created",
            "sandbox.lifecycle.updated",
            "sandbox.lifecycle.killed",
        ],
    }

    try:
        result = _e2b_webhook_request("POST", "", api_key, payload)
        webhook_id = result.get("id") if isinstance(result, dict) else None
        logger.info(
            "Auto-registered E2B webhook: id=%s url=%s", webhook_id, webhook_url
        )
        return webhook_id
    except Exception:
        logger.warning("Failed to auto-register E2B webhook", exc_info=True)
        return None


def _auto_deregister_webhook(webhook_id: str | None) -> None:
    """Deregister the auto-registered E2B webhook (best-effort cleanup)."""
    if webhook_id is None:
        return
    try:
        api_key = os.environ.get("E2B_API_KEY", "")
        _e2b_webhook_request("DELETE", f"/{webhook_id}", api_key)
        logger.info("Deregistered E2B webhook: id=%s", webhook_id)
    except Exception:
        logger.warning(
            "Failed to deregister E2B webhook id=%s", webhook_id, exc_info=True
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_telemetry(app)
    webhook_id = _auto_register_webhook()
    yield
    _auto_deregister_webhook(webhook_id)


app = FastAPI(title="Sandstorm", lifespan=lifespan)

cors_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhooks/e2b")
async def e2b_webhook(request: Request):
    """Receive E2B sandbox lifecycle events for logging and diagnostics."""
    body = await request.body()

    with get_tracer().start_as_current_span("webhook.e2b") as span:
        # Verify HMAC signature when a secret is configured
        if _WEBHOOK_SECRET:
            raw_signature = request.headers.get("e2b-signature", "")
            # Strip optional "sha256=" prefix (common webhook convention)
            signature = raw_signature.removeprefix("sha256=")
            expected = hmac.new(
                _WEBHOOK_SECRET.encode(), body, hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(signature, expected):
                logger.warning("E2B webhook: invalid signature — rejecting")
                sig_err = ValueError("invalid webhook signature")
                set_span_error(span, sig_err)
                record_error(error_type="webhook_signature")
                return JSONResponse({"error": "invalid signature"}, status_code=401)

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            set_span_error(span, exc)
            record_error(error_type="webhook_json")
            return JSONResponse({"error": "invalid JSON"}, status_code=400)

        event_type = payload.get("type", "unknown")
        sandbox_id = payload.get("sandboxId", "unknown")
        metadata = payload.get("eventData", {}).get("sandbox_metadata", {}) or {}
        request_id = metadata.get("request_id", "unknown")

        span.set_attribute("sandstorm.webhook.event_type", event_type)
        span.set_attribute("sandstorm.sandbox_id", sandbox_id)
        span.set_attribute("sandstorm.request_id", request_id)

        logger.info(
            "[%s] E2B lifecycle event: %s sandbox=%s",
            request_id,
            event_type,
            sandbox_id,
        )

        record_webhook_event(event_type=event_type)
        return {"status": "ok"}


@app.post("/query")
async def query(request: QueryRequest):
    req_id = uuid.uuid4().hex[:8]
    logger.info(
        "[%s] Query received: prompt=%s model=%s",
        req_id,
        request.prompt[:80],
        request.model,
    )

    async def event_generator():
        start = time.monotonic()
        with get_tracer().start_as_current_span(
            "query",
            attributes={
                "sandstorm.request_id": req_id,
                "sandstorm.model": request.model or "",
                "sandstorm.timeout": request.timeout,
                "sandstorm.file_count": len(request.files) if request.files else 0,
            },
        ) as span:
            try:
                async for line in run_agent_in_sandbox(request, req_id):
                    yield {"data": line}
            except (RuntimeError, SandboxException, AuthenticationException) as e:
                set_span_error(span, e)
                record_error(error_type=type(e).__name__)
                record_request(model=request.model, status="error")
                logger.error("[%s] Query failed: %s", req_id, e, exc_info=True)
                yield {
                    "data": json.dumps(
                        {"type": "error", "error": str(e), "request_id": req_id}
                    )
                }
            else:
                record_request(model=request.model, status="ok")
                logger.info("[%s] Query completed", req_id)
            finally:
                record_request_duration(time.monotonic() - start, model=request.model)

    return EventSourceResponse(event_generator(), ping=30)
