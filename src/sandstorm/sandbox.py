"""E2B sandbox lifecycle: create, run agent, stream output, cleanup."""

import asyncio
import contextlib
import json
import logging
import os
import posixpath
import shlex
import time
from collections.abc import AsyncGenerator
from importlib.resources import files as pkg_files
from pathlib import Path

from e2b import AsyncSandbox, NotFoundException

from .config import _PROVIDER_ENV_KEYS, _build_agent_config, load_sandstorm_config
from .files import _extract_generated_files, _load_skills_dir, _upload_files, _upload_skills
from .models import QueryRequest
from .telemetry import (
    get_tracer,
    record_agent_execution,
    record_queue_drop,
    record_sandbox_creation,
    sandbox_started,
    sandbox_stopped,
)

logger = logging.getLogger(__name__)

# Custom template with Agent SDK pre-installed (built via build_template.py).
# Falls back to E2B's "claude-code" template + runtime install if custom not found.
TEMPLATE = os.environ.get("SANDSTORM_TEMPLATE", "work-43ca/sandstorm")
FALLBACK_TEMPLATE = "claude-code"

# Claude Agent SDK version — single source of truth (also imported by build_template.py)
SDK_VERSION = "0.2.42"

_QUEUE_MAXSIZE = 10_000  # Buffer for sync→async bridge; drops if consumer is slow
_SDK_INSTALL_TIMEOUT = 120  # Fallback npm install timeout (seconds)
_RUNNER_TIMEOUT = 1800  # Max agent execution time (30 minutes)

# Path inside the sandbox where GCP credentials are uploaded
_GCP_CREDENTIALS_SANDBOX_PATH = "/home/user/.config/gcloud/service_account.json"

# Load the runner script that executes inside the sandbox
_RUNNER_SCRIPT = pkg_files("sandstorm").joinpath("runner.mjs").read_text()


def _read_gcp_credentials() -> str | None:
    """Read GCP service account JSON if Vertex AI is configured."""
    if not os.environ.get("CLAUDE_CODE_USE_VERTEX"):
        return None

    gcp_creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not gcp_creds_path:
        raise RuntimeError(
            "GOOGLE_APPLICATION_CREDENTIALS is required when using Vertex AI — "
            "set it in .env to the path of your GCP service account JSON key"
        )
    creds_file = Path(gcp_creds_path)
    if not creds_file.is_absolute():
        creds_file = Path.cwd() / creds_file
    try:
        return creds_file.read_text()
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"GOOGLE_APPLICATION_CREDENTIALS file not found: {gcp_creds_path}"
        ) from exc


async def _create_sandbox(
    api_key: str | None,
    timeout: int,
    envs: dict[str, str],
    request_id: str,
) -> AsyncSandbox:
    """Create sandbox, falling back to base template + runtime SDK install."""
    with get_tracer().start_as_current_span(
        "sandbox.create", attributes={"sandstorm.template": TEMPLATE}
    ) as span:
        start = time.monotonic()
        logger.info("[%s] Creating sandbox template=%s", request_id, TEMPLATE)
        used_fallback = False
        try:
            sbx = await AsyncSandbox.create(
                template=TEMPLATE,
                api_key=api_key,
                timeout=timeout,
                envs=envs,
                metadata={"request_id": request_id},
            )
        except NotFoundException:
            used_fallback = True
            span.set_attribute("sandstorm.template_fallback", True)
            logger.warning(
                "[%s] Template %r not found, falling back to %r (adds ~15s overhead)",
                request_id,
                TEMPLATE,
                FALLBACK_TEMPLATE,
            )
            sbx = await AsyncSandbox.create(
                template=FALLBACK_TEMPLATE,
                api_key=api_key,
                timeout=timeout,
                envs=envs,
                metadata={"request_id": request_id},
            )
            await sbx.commands.run(
                "mkdir -p /opt/agent-runner"
                " && cd /opt/agent-runner"
                " && npm init -y"
                f" && npm install @anthropic-ai/claude-agent-sdk@{SDK_VERSION}",
                timeout=_SDK_INSTALL_TIMEOUT,
            )
        duration = time.monotonic() - start
        span.set_attribute("sandstorm.template_fallback", used_fallback)
        span.set_attribute("sandstorm.sandbox_id", sbx.sandbox_id)
        record_sandbox_creation(
            duration, template=FALLBACK_TEMPLATE if used_fallback else TEMPLATE
        )
        sandbox_started()
        logger.info("[%s] Sandbox created: %s", request_id, sbx.sandbox_id)
        return sbx


async def _cleanup(task: asyncio.Task | None, sbx: AsyncSandbox, request_id: str) -> None:
    """Cancel the background command task and destroy the sandbox."""
    with get_tracer().start_as_current_span(
        "sandbox.cleanup",
        attributes={"sandstorm.sandbox_id": sbx.sandbox_id},
    ):
        # task may be None if an error occurred before create_task()
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        elif task is not None:
            # Task finished — suppress any command exit exception
            try:
                task.result()
            except Exception:
                logger.warning(
                    "[%s] Task exception suppressed (runner likely streamed the error)",
                    request_id,
                    exc_info=True,
                )
        logger.info("[%s] Destroying sandbox %s", request_id, sbx.sandbox_id)
        await sbx.kill()


def _to_str(data) -> str:
    """Coerce callback data to str (E2B may pass non-string types)."""
    return data if isinstance(data, str) else str(data)


async def run_agent_in_sandbox(
    request: QueryRequest,
    request_id: str = "",
    *,
    keep_alive: bool = False,
    sandbox_id: str | None = None,
    sandbox_id_out: list[str] | None = None,
    binary_files: dict[str, bytes] | None = None,
) -> AsyncGenerator[str, None]:
    """Create an E2B sandbox, run the Claude Agent SDK query(), and yield messages."""
    queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
    _queue_full_warned = False

    def _enqueue(data: str) -> None:
        """Put data on the queue, dropping if full (sync callbacks can't await)."""
        nonlocal _queue_full_warned
        try:
            queue.put_nowait(data)
        except asyncio.QueueFull:
            record_queue_drop()
            if not _queue_full_warned:
                _queue_full_warned = True
                logger.warning(
                    "[%s] Queue full (maxsize=%d), dropping messages — consumer can't keep up",
                    request_id,
                    queue.maxsize,
                )
                # Notify client via SSE so they know data was lost
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(
                        json.dumps(
                            {
                                "type": "warning",
                                "message": "Output buffer full, some messages may be dropped",
                            }
                        )
                    )

    sandstorm_config = load_sandstorm_config() or {}
    task = None

    # Load skills from skills_dir (needed by both paths for _build_agent_config)
    disk_skills: dict[str, dict[str, str]] = {}
    if sandstorm_config.get("skills_dir"):
        disk_skills.update(_load_skills_dir(sandstorm_config["skills_dir"]))

    agent_config, merged_skills = _build_agent_config(request, sandstorm_config, disk_skills)
    has_skills = agent_config["has_skills"]
    timeout = agent_config["timeout"]

    # Track input file names to exclude from file extraction later
    input_file_names: set[str] = set()
    if request.files:
        input_file_names.update(request.files.keys())
    if binary_files:
        input_file_names.update(binary_files.keys())

    if sandbox_id:
        # --- Reconnect path: reuse an existing sandbox ---
        logger.info("[%s] Reconnecting to sandbox %s", request_id, sandbox_id)
        sbx = await AsyncSandbox.connect(sandbox_id, api_key=request.e2b_api_key)
        await sbx.set_timeout(timeout)
        sandbox_started()

        # Upload extra skills that aren't already in the sandbox
        extra_skills_to_upload = {k: v for k, v in merged_skills.items() if k not in disk_skills}
        if extra_skills_to_upload:
            await _upload_skills(sbx, extra_skills_to_upload, request_id)

        # Upload user files if provided
        if request.files:
            await _upload_files(sbx, request.files, request_id)
        if binary_files:
            logger.info("[%s] Uploading %d binary files", request_id, len(binary_files))
            await sbx.files.write_files(
                [
                    {"path": f"/home/user/{path}", "data": data}
                    for path, data in binary_files.items()
                ]
            )

        # Write new agent_config with the new prompt
        await sbx.files.write_files(
            [
                {
                    "path": "/opt/agent-runner/agent_config.json",
                    "data": json.dumps(agent_config),
                },
            ]
        )
    else:
        # --- Normal create path ---
        # Build sandbox env vars: API key + any provider env vars from .env
        sandbox_envs: dict[str, str] = {}
        if request.anthropic_api_key:
            sandbox_envs["ANTHROPIC_API_KEY"] = request.anthropic_api_key
        for key in _PROVIDER_ENV_KEYS:
            val = os.environ.get(key)
            if val:
                sandbox_envs[key] = val

        # Per-request OpenRouter key overrides env var
        if request.openrouter_api_key:
            sandbox_envs["ANTHROPIC_AUTH_TOKEN"] = request.openrouter_api_key

        # When using a custom base URL with auth token (e.g. OpenRouter), the SDK
        # must NOT receive a real ANTHROPIC_API_KEY — otherwise it validates model
        # names against Anthropic's API and rejects non-Claude models.
        if sandbox_envs.get("ANTHROPIC_BASE_URL") and sandbox_envs.get("ANTHROPIC_AUTH_TOKEN"):
            sandbox_envs["ANTHROPIC_API_KEY"] = ""

        # Eagerly read GCP credentials (TOCTOU fix: read now, upload later)
        gcp_creds_content = _read_gcp_credentials()
        if gcp_creds_content:
            sandbox_envs["GOOGLE_APPLICATION_CREDENTIALS"] = _GCP_CREDENTIALS_SANDBOX_PATH

        sbx = await _create_sandbox(request.e2b_api_key, timeout, sandbox_envs, request_id)
        if sandbox_id_out is not None:
            sandbox_id_out.append(sbx.sandbox_id)

    try:
        if not sandbox_id:
            # Full setup only needed for fresh sandboxes
            # Build Claude Agent SDK settings
            settings: dict = {
                "permissions": {"allow": [], "deny": []},
            }
            if not has_skills:
                settings["env"] = {"CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1"}

            # Create all needed directories in a single command
            dirs = ["/home/user/.claude"]
            if gcp_creds_content:
                dirs.append(posixpath.dirname(_GCP_CREDENTIALS_SANDBOX_PATH))
            await sbx.commands.run(
                " && ".join(f"mkdir -p {shlex.quote(d)}" for d in dirs),
                timeout=5,
            )

            # Upload skills (batch mkdir + batch write)
            # When template_skills is set, disk skills are already baked into the
            # sandbox image — only upload extra skills that aren't in the template.
            skills_to_upload = merged_skills
            if sandstorm_config.get("template_skills"):
                skills_to_upload = {k: v for k, v in merged_skills.items() if k not in disk_skills}
            if skills_to_upload:
                await _upload_skills(sbx, skills_to_upload, request_id)

            # Upload user files (batch write)
            if request.files:
                await _upload_files(sbx, request.files, request_id)
            if binary_files:
                logger.info("[%s] Uploading %d binary files", request_id, len(binary_files))
                await sbx.files.write_files(
                    [
                        {"path": f"/home/user/{path}", "data": data}
                        for path, data in binary_files.items()
                    ]
                )

            # Batch-write all infrastructure files in a single API call
            if gcp_creds_content:
                logger.info("[%s] Uploading GCP credentials to sandbox", request_id)
            await sbx.files.write_files(
                [
                    {
                        "path": "/home/user/.claude/settings.json",
                        "data": json.dumps(settings, indent=2),
                    },
                    {"path": "/opt/agent-runner/runner.mjs", "data": _RUNNER_SCRIPT},
                    {
                        "path": "/opt/agent-runner/agent_config.json",
                        "data": json.dumps(agent_config),
                    },
                    *(
                        [{"path": _GCP_CREDENTIALS_SANDBOX_PATH, "data": gcp_creds_content}]
                        if gcp_creds_content
                        else []
                    ),
                ]
            )

        # Run the SDK query() via the runner script
        logger.info(
            "[%s] Starting agent (model=%s, max_turns=%s)",
            request_id,
            agent_config.get("model"),
            agent_config.get("max_turns"),
        )

        def _on_stdout(data):
            _enqueue(_to_str(data))

        def _on_stderr(data):
            text = _to_str(data).strip()
            if text:
                _enqueue(json.dumps({"type": "stderr", "data": text}))

        async def run_command():
            try:
                await sbx.commands.run(
                    "node /opt/agent-runner/runner.mjs",
                    timeout=_RUNNER_TIMEOUT,
                    on_stdout=_on_stdout,
                    on_stderr=_on_stderr,
                )
            finally:
                await queue.put(None)

        agent_start = time.monotonic()
        with get_tracer().start_as_current_span(
            "agent.execute",
            attributes={
                "sandstorm.model": agent_config.get("model") or "",
                "sandstorm.sandbox_id": sbx.sandbox_id,
                "sandstorm.has_skills": has_skills,
            },
        ):
            task = asyncio.create_task(run_command())

            # Yield messages from queue until the process ends
            while True:
                line = await queue.get()
                if line is None:
                    break
                line = line.strip()
                if line:
                    yield line

            record_agent_execution(
                time.monotonic() - agent_start,
                model=agent_config.get("model"),
            )

        # Extract files created by the agent (sandbox still alive)
        try:
            generated = await _extract_generated_files(sbx, input_file_names, request_id)
            for file_event in generated:
                yield file_event
        except Exception:
            logger.warning("[%s] File extraction failed", request_id, exc_info=True)

    finally:
        sandbox_stopped()
        if keep_alive:
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            elif task is not None:
                try:
                    task.result()
                except Exception:
                    logger.warning("[%s] Task exception suppressed", request_id, exc_info=True)
            logger.info(
                "[%s] Keeping sandbox %s alive (timeout=%ds)",
                request_id,
                sbx.sandbox_id,
                timeout,
            )
        else:
            await _cleanup(task, sbx, request_id)
