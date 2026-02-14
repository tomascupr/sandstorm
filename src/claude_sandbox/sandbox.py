import asyncio
import json
import os
from collections.abc import AsyncGenerator
from importlib.resources import files
from pathlib import Path

from e2b import AsyncSandbox

from .models import QueryRequest

# Custom template with Agent SDK pre-installed (built via build_template.py).
# Falls back to E2B's "claude-code" template + runtime install if custom not found.
TEMPLATE = "work-43ca/sandstorm"
FALLBACK_TEMPLATE = "claude-code"

# Load the runner script that executes inside the sandbox
_RUNNER_SCRIPT = files("claude_sandbox").joinpath("runner.mjs").read_text()

# Path to project-level sandstorm config (resolved relative to this file)
_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "sandstorm.json"

# Provider env vars auto-forwarded from .env into the sandbox
_PROVIDER_ENV_KEYS = [
    # Google Vertex AI
    "CLAUDE_CODE_USE_VERTEX", "CLOUD_ML_REGION", "ANTHROPIC_VERTEX_PROJECT_ID",
    # Amazon Bedrock
    "CLAUDE_CODE_USE_BEDROCK", "AWS_REGION", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    # Microsoft Azure / Foundry
    "CLAUDE_CODE_USE_FOUNDRY", "AZURE_FOUNDRY_RESOURCE", "AZURE_API_KEY",
    # Custom base URL (proxy, self-hosted)
    "ANTHROPIC_BASE_URL",
]


def _load_sandstorm_config() -> dict | None:
    """Load sandstorm.json from the project root if it exists."""
    if _CONFIG_PATH.exists():
        return json.loads(_CONFIG_PATH.read_text())
    return None


async def run_agent_in_sandbox(request: QueryRequest) -> AsyncGenerator[str, None]:
    """Create an E2B sandbox, run the Claude Agent SDK query(), and yield messages."""
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    # Build sandbox env vars: API key + any provider env vars from .env
    sandbox_envs = {"ANTHROPIC_API_KEY": request.anthropic_api_key}
    for key in _PROVIDER_ENV_KEYS:
        val = os.environ.get(key)
        if val:
            sandbox_envs[key] = val

    sandstorm_config = _load_sandstorm_config() or {}

    try:
        sbx = await AsyncSandbox.create(
            template=TEMPLATE,
            api_key=request.e2b_api_key,
            timeout=request.timeout,
            envs=sandbox_envs,
        )
    except Exception:
        # Fall back to default template + runtime install of the SDK
        sbx = await AsyncSandbox.create(
            template=FALLBACK_TEMPLATE,
            api_key=request.e2b_api_key,
            timeout=request.timeout,
            envs=sandbox_envs,
        )
        await sbx.commands.run(
            "mkdir -p /opt/agent-runner"
            " && cd /opt/agent-runner"
            " && npm init -y"
            " && npm install @anthropic-ai/claude-agent-sdk@latest",
            timeout=120,
        )

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

        # Upload user files to the sandbox (path traversal prevented by model validation)
        if request.files:
            for path, content in request.files.items():
                await sbx.files.write(f"/home/user/{path}", content)

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
        await sbx.files.write("/opt/agent-runner/agent_config.json", json.dumps(agent_config))

        # Run the SDK query() via the runner script
        async def run_command():
            try:
                await sbx.commands.run(
                    "node /opt/agent-runner/runner.mjs",
                    timeout=1800,
                    on_stdout=lambda data: queue.put_nowait(
                        data if isinstance(data, str) else str(data)
                    ),
                    on_stderr=lambda data: None,
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

        # Suppress expected command exit exceptions (errors already streamed by runner)
        try:
            await task
        except Exception:
            pass

    finally:
        await sbx.kill()
