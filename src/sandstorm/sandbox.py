import asyncio
import contextlib
import json
import logging
import os
import posixpath
import re
import shlex
import time
from collections.abc import AsyncGenerator
from importlib.resources import files
from pathlib import Path

from e2b import AsyncSandbox, NotFoundException

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
_SKILL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

# Load the runner script that executes inside the sandbox
_RUNNER_SCRIPT = files("sandstorm").joinpath("runner.mjs").read_text()


def _get_config_path() -> Path:
    """Resolve sandstorm.json from the current working directory."""
    return Path.cwd() / "sandstorm.json"


# Path inside the sandbox where GCP credentials are uploaded
_GCP_CREDENTIALS_SANDBOX_PATH = "/home/user/.config/gcloud/service_account.json"

# Provider env vars auto-forwarded from .env into the sandbox
_PROVIDER_ENV_KEYS = [
    # Google Vertex AI
    "CLAUDE_CODE_USE_VERTEX",
    "CLOUD_ML_REGION",
    "ANTHROPIC_VERTEX_PROJECT_ID",
    # Amazon Bedrock
    "CLAUDE_CODE_USE_BEDROCK",
    "AWS_REGION",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    # Microsoft Azure / Foundry
    "CLAUDE_CODE_USE_FOUNDRY",
    "AZURE_FOUNDRY_RESOURCE",
    "AZURE_API_KEY",
    # Custom base URL (proxy, self-hosted, OpenRouter)
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    # Model name overrides (remap SDK aliases to provider model IDs)
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
]


def _validate_sandstorm_config(raw: dict) -> dict:
    """Validate known sandstorm.json fields, drop invalid ones with warnings."""
    # Expected field types: field_name -> (allowed types tuple, human description)
    known_fields: dict[str, tuple[tuple[type, ...], str]] = {
        "system_prompt": ((str,), "str"),
        "model": ((str,), "str"),
        "max_turns": ((int,), "int"),
        "output_format": ((dict,), "dict"),
        "agents": ((dict, list), "dict or list"),
        "mcp_servers": ((dict,), "dict"),
        "skills_dir": ((str,), "str"),
        "allowed_tools": ((list,), "list"),
        "webhook_url": ((str,), "str"),
    }

    validated: dict = {}
    for key, value in raw.items():
        if key in known_fields:
            allowed_types, type_desc = known_fields[key]
            # Reject booleans masquerading as int (isinstance(True, int) is True)
            if isinstance(value, bool) and bool not in allowed_types:
                logger.warning(
                    "sandstorm.json: field %r should be %s, got bool — skipping",
                    key,
                    type_desc,
                )
                continue
            if not isinstance(value, allowed_types):
                logger.warning(
                    "sandstorm.json: field %r should be %s, got %s — skipping",
                    key,
                    type_desc,
                    type(value).__name__,
                )
                continue
            validated[key] = value
        else:
            logger.warning("sandstorm.json: unknown field %r — ignoring", key)

    if "skills_dir" in validated:
        skills_dir_path = Path.cwd() / validated["skills_dir"]
        if not skills_dir_path.is_dir():
            logger.warning(
                "sandstorm.json: skills_dir %r does not exist — ignoring",
                validated["skills_dir"],
            )
            del validated["skills_dir"]

    if "allowed_tools" in validated and not all(
        isinstance(t, str) for t in validated["allowed_tools"]
    ):
        logger.warning("sandstorm.json: allowed_tools entries must be strings — skipping")
        del validated["allowed_tools"]

    return validated


def load_sandstorm_config() -> dict | None:
    """Load sandstorm.json from the project root if it exists."""
    config_path = _get_config_path()
    if not config_path.exists():
        return None

    try:
        raw = json.loads(config_path.read_text())
    except json.JSONDecodeError as exc:
        logger.error("sandstorm.json: invalid JSON — %s", exc)
        return None

    if not isinstance(raw, dict):
        logger.error("sandstorm.json: expected a JSON object, got %s", type(raw).__name__)
        return None

    return _validate_sandstorm_config(raw)


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


async def _upload_files(sbx: AsyncSandbox, files: dict[str, str], request_id: str) -> None:
    """Upload user files to the sandbox, creating parent directories as needed."""
    total_size = sum(len(c.encode()) for c in files.values())
    with get_tracer().start_as_current_span(
        "sandbox.upload_files",
        attributes={
            "sandstorm.file_count": len(files),
            "sandstorm.total_size_bytes": total_size,
        },
    ):
        logger.info("[%s] Uploading %d files", request_id, len(files))
        # Collect parent dirs that need creation (deduplicate, skip top-level files)
        dirs_to_create: set[str] = set()
        for path in files:
            parent = posixpath.dirname(path)
            if parent:  # non-empty means nested path like "src/main.py"
                dirs_to_create.add(f"/home/user/{parent}")

        if dirs_to_create:
            mkdir_cmd = " && ".join(f"mkdir -p {shlex.quote(d)}" for d in sorted(dirs_to_create))
            await sbx.commands.run(mkdir_cmd, timeout=10)

        try:
            await sbx.files.write_files(
                [
                    {"path": f"/home/user/{path}", "data": content}
                    for path, content in files.items()
                ]
            )
        except Exception as exc:
            paths = ", ".join(files.keys())
            raise RuntimeError(
                f"Failed to upload {len(files)} files ({paths}) to sandbox: {exc}"
            ) from exc


def _load_skills_dir(skills_dir: str) -> dict[str, str]:
    """Read SKILL.md files from a host directory into {name: content} dict."""
    base = Path.cwd() / skills_dir
    skills: dict[str, str] = {}
    if not base.is_dir():
        return skills
    for entry in base.iterdir():
        if not entry.is_dir():
            continue
        if not _SKILL_NAME_PATTERN.match(entry.name):
            logger.warning("skills_dir: skipping %r (invalid name)", entry.name)
            continue
        skill_file = entry / "SKILL.md"
        if skill_file.is_file():
            skills[entry.name] = skill_file.read_text()
    return skills


async def _upload_skills(sbx: AsyncSandbox, skills: dict[str, str], request_id: str) -> None:
    """Upload skills to /home/user/.claude/skills/<name>/SKILL.md in the sandbox."""
    with get_tracer().start_as_current_span(
        "sandbox.upload_skills",
        attributes={"sandstorm.skill_count": len(skills)},
    ):
        logger.info("[%s] Uploading %d skills", request_id, len(skills))
        # Create all skill directories in a single command
        dirs = [f"/home/user/.claude/skills/{name}" for name in skills]
        mkdir_cmd = " && ".join(f"mkdir -p {shlex.quote(d)}" for d in dirs)
        await sbx.commands.run(mkdir_cmd, timeout=5)
        # Batch write all skill files
        try:
            await sbx.files.write_files(
                [
                    {
                        "path": f"/home/user/.claude/skills/{name}/SKILL.md",
                        "data": content,
                    }
                    for name, content in skills.items()
                ]
            )
        except Exception as exc:
            names = ", ".join(skills.keys())
            raise RuntimeError(
                f"Failed to upload {len(skills)} skills ({names}) to sandbox: {exc}"
            ) from exc


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
    request: QueryRequest, request_id: str = ""
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

    sandstorm_config = load_sandstorm_config() or {}

    sbx = await _create_sandbox(request.e2b_api_key, request.timeout, sandbox_envs, request_id)

    task = None
    try:
        # Load skills from skills_dir
        merged_skills: dict[str, str] = {}
        if sandstorm_config.get("skills_dir"):
            merged_skills.update(_load_skills_dir(sandstorm_config["skills_dir"]))

        has_skills = bool(merged_skills)

        # Build Claude Agent SDK settings
        settings: dict = {
            "permissions": {"allow": [], "deny": []},
        }
        if not has_skills:
            settings["env"] = {"CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1"}

        # Auto-add "Skill" to allowed_tools if user set allowed_tools but forgot it
        allowed_tools = sandstorm_config.get("allowed_tools")
        if allowed_tools is not None and has_skills and "Skill" not in allowed_tools:
            allowed_tools = [*allowed_tools, "Skill"]

        # Build agent config: sandstorm.json (base) + request overrides
        agent_config = {
            "prompt": request.prompt,
            "cwd": "/home/user",
            # Request overrides sandstorm.json
            "model": request.model or sandstorm_config.get("model"),
            "max_turns": request.max_turns or sandstorm_config.get("max_turns"),
            # These come from sandstorm.json only
            "system_prompt": sandstorm_config.get("system_prompt"),
            "output_format": sandstorm_config.get("output_format"),
            "agents": sandstorm_config.get("agents"),
            "mcp_servers": sandstorm_config.get("mcp_servers"),
            # Skills configuration
            "has_skills": has_skills,
            "allowed_tools": allowed_tools,
        }

        # Create all needed directories in a single command
        dirs = ["/home/user/.claude"]
        if gcp_creds_content:
            dirs.append(posixpath.dirname(_GCP_CREDENTIALS_SANDBOX_PATH))
        await sbx.commands.run(
            " && ".join(f"mkdir -p {shlex.quote(d)}" for d in dirs),
            timeout=5,
        )

        # Upload skills (batch mkdir + batch write)
        if merged_skills:
            await _upload_skills(sbx, merged_skills, request_id)

        # Upload user files (batch write)
        if request.files:
            await _upload_files(sbx, request.files, request_id)

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

    finally:
        sandbox_stopped()
        await _cleanup(task, sbx, request_id)
