import json
import logging
import os
import time
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from e2b import AuthenticationException, SandboxException

from . import _LOG_DATEFMT, _LOG_FORMAT
from .models import QueryRequest
from .sandbox import run_agent_in_sandbox
from .telemetry import (
    init as init_telemetry,
    get_tracer,
    set_span_error,
    record_request,
    record_request_duration,
    record_error,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format=_LOG_FORMAT,
    datefmt=_LOG_DATEFMT,
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Sandstorm")

cors_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

init_telemetry(app)


@app.get("/health")
async def health():
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
