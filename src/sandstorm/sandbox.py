import asyncio
import json
import logging
import os
import posixpath
import shlex
from collections.abc import AsyncGenerator
from importlib.resources import files
from pathlib import Path

from e2b import AsyncSandbox, NotFoundException

from .models import QueryRequest

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

    return validated


def _load_sandstorm_config() -> dict | None:
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
        logger.error(
            "sandstorm.json: expected a JSON object, got %s", type(raw).__name__
        )
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
    except FileNotFoundError:
        raise RuntimeError(
            f"GOOGLE_APPLICATION_CREDENTIALS file not found: {gcp_creds_path}"
        )


async def _create_sandbox(
    api_key: str | None,
    timeout: int,
    envs: dict[str, str],
    request_id: str,
) -> AsyncSandbox:
    """Create sandbox, falling back to base template + runtime SDK install."""
    logger.info("[%s] Creating sandbox template=%s", request_id, TEMPLATE)
    try:
        sbx = await AsyncSandbox.create(
            template=TEMPLATE,
            api_key=api_key,
            timeout=timeout,
            envs=envs,
        )
    except NotFoundException:
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
        )
        await sbx.commands.run(
            "mkdir -p /opt/agent-runner"
            " && cd /opt/agent-runner"
            " && npm init -y"
            f" && npm install @anthropic-ai/claude-agent-sdk@{SDK_VERSION}",
            timeout=_SDK_INSTALL_TIMEOUT,
        )
    logger.info("[%s] Sandbox created: %s", request_id, sbx.sandbox_id)
    return sbx


async def _upload_files(
    sbx: AsyncSandbox, files: dict[str, str], request_id: str
) -> None:
    """Upload user files to the sandbox, creating parent directories as needed."""
    logger.info("[%s] Uploading %d files", request_id, len(files))
    # Collect parent dirs that need creation (deduplicate, skip top-level files)
    dirs_to_create: set[str] = set()
    for path in files:
        parent = posixpath.dirname(path)
        if parent:  # non-empty means nested path like "src/main.py"
            dirs_to_create.add(f"/home/user/{parent}")

    if dirs_to_create:
        mkdir_cmd = " && ".join(
            f"mkdir -p {shlex.quote(d)}" for d in sorted(dirs_to_create)
        )
        await sbx.commands.run(mkdir_cmd, timeout=10)

    for path, content in files.items():
        sandbox_path = f"/home/user/{path}"
        try:
            await sbx.files.write(sandbox_path, content)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to upload file {path!r} to sandbox: {exc}"
            ) from exc


async def _cleanup(
    task: asyncio.Task | None, sbx: AsyncSandbox, request_id: str
) -> None:
    """Cancel the background command task and destroy the sandbox."""
    # task may be None if an error occurred before create_task()
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
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
            if not _queue_full_warned:
                logger.warning(
                    "[%s] Queue full (maxsize=%d), dropping messages — consumer can't keep up",
                    request_id,
                    queue.maxsize,
                )
                _queue_full_warned = True

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
    if sandbox_envs.get("ANTHROPIC_BASE_URL") and sandbox_envs.get(
        "ANTHROPIC_AUTH_TOKEN"
    ):
        sandbox_envs["ANTHROPIC_API_KEY"] = ""

    # Eagerly read GCP credentials (TOCTOU fix: read now, upload later)
    gcp_creds_content = _read_gcp_credentials()
    if gcp_creds_content:
        sandbox_envs["GOOGLE_APPLICATION_CREDENTIALS"] = _GCP_CREDENTIALS_SANDBOX_PATH

    sandstorm_config = _load_sandstorm_config() or {}

    sbx = await _create_sandbox(
        request.e2b_api_key, request.timeout, sandbox_envs, request_id
    )

    task = None
    try:
        # Write Claude Agent SDK settings to the sandbox
        settings = {
            "permissions": {"allow": [], "deny": []},
            "env": {"CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1"},
        }
        await sbx.commands.run("mkdir -p /home/user/.claude", timeout=5)
        await sbx.files.write(
            "/home/user/.claude/settings.json",
            json.dumps(settings, indent=2),
        )

        # Upload GCP credentials to the sandbox if Vertex AI is configured
        if gcp_creds_content:
            logger.info("[%s] Uploading GCP credentials to sandbox", request_id)
            await sbx.commands.run(
                f"mkdir -p {posixpath.dirname(_GCP_CREDENTIALS_SANDBOX_PATH)}",
                timeout=5,
            )
            await sbx.files.write(_GCP_CREDENTIALS_SANDBOX_PATH, gcp_creds_content)

        # Upload user files (path traversal prevented by model validation)
        if request.files:
            await _upload_files(sbx, request.files, request_id)

        # Upload runner script
        await sbx.files.write("/opt/agent-runner/runner.mjs", _RUNNER_SCRIPT)

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
        }
        await sbx.files.write(
            "/opt/agent-runner/agent_config.json", json.dumps(agent_config)
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

        task = asyncio.create_task(run_command())

        # Yield messages from queue until the process ends
        while True:
            line = await queue.get()
            if line is None:
                break
            line = line.strip()
            if line:
                yield line

    finally:
        await _cleanup(task, sbx, request_id)
