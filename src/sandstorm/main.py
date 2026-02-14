import json
import logging
import os
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from .models import QueryRequest
from .sandbox import run_agent_in_sandbox

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
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


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "env": {
            "ANTHROPIC_API_KEY": "set"
            if os.environ.get("ANTHROPIC_API_KEY")
            else "not set",
            "ANTHROPIC_BASE_URL": "set"
            if os.environ.get("ANTHROPIC_BASE_URL")
            else "not set",
            "OPENROUTER_API_KEY": "set"
            if os.environ.get("OPENROUTER_API_KEY")
            else "not set",
            "E2B_API_KEY": "set" if os.environ.get("E2B_API_KEY") else "not set",
        },
    }


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
        try:
            async for line in run_agent_in_sandbox(request, req_id):
                yield {"data": line}
        except Exception as e:
            logger.error("[%s] Query failed: %s", req_id, e, exc_info=True)
            yield {
                "data": json.dumps(
                    {"type": "error", "error": str(e), "request_id": req_id}
                )
            }
        else:
            logger.info("[%s] Query completed", req_id)

    return EventSourceResponse(event_generator(), ping=30)
