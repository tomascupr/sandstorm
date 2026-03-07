"""Sandstorm configuration loading, validation, and agent config building."""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from dotenv import load_dotenv as _load_dotenv

from .models import NAME_PATTERN, QueryRequest

logger = logging.getLogger(__name__)

# Regex for valid skill names (re-exported from models for convenience)
_SKILL_NAME_PATTERN = NAME_PATTERN

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
    # MCP providers that rely on inherited sandbox env vars
    "LINEAR_API_KEY",
    # Model name overrides (remap SDK aliases to provider model IDs)
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
]

_MCP_ENV_VAR_PATTERN = re.compile(
    r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::-(?P<default>[^}]*))?\}"
)
_LOADED_DOTENV_VALUES: dict[str, str] = {}

# ── mtime-based config cache ──────────────────────────────────────────────────

_config_cache: dict | None = None
_config_mtime: float = 0.0


def _get_config_path() -> Path:
    """Resolve sandstorm.json from the current working directory."""
    return Path.cwd() / "sandstorm.json"


def _get_env_path() -> Path:
    """Resolve the project-local .env from the current working directory."""
    return Path.cwd() / ".env"


def _read_project_dotenv() -> dict[str, str]:
    """Read the current project .env file without mutating process env."""
    env_path = _get_env_path()
    if not env_path.is_file():
        return {}
    return {key: value for key, value in dotenv_values(env_path).items() if value is not None}


def load_project_dotenv(*args: Any, **kwargs: Any) -> bool:
    """Load dotenv values and track which project-local keys came from .env."""
    global _LOADED_DOTENV_VALUES

    if not args and "dotenv_path" not in kwargs and "stream" not in kwargs:
        kwargs = {**kwargs, "dotenv_path": _get_env_path()}

    current = _read_project_dotenv()
    previous_env = {key: os.environ.get(key) for key in current}
    override = bool(kwargs.get("override", False))

    loaded = _load_dotenv(*args, **kwargs)
    _LOADED_DOTENV_VALUES = {
        key: value
        for key, value in _read_project_dotenv().items()
        if os.environ.get(key) == value
        and (
            key in _LOADED_DOTENV_VALUES
            or previous_env.get(key) is None
            or (override and previous_env.get(key) != value)
        )
    }
    return loaded


def _refresh_project_dotenv() -> None:
    """Hot-reload project .env values while preserving explicit process env vars."""
    global _LOADED_DOTENV_VALUES

    current = _read_project_dotenv()

    previous_loaded = _LOADED_DOTENV_VALUES

    for key, previous in previous_loaded.items():
        if key not in current and os.environ.get(key) == previous:
            os.environ.pop(key, None)

    loaded_values: dict[str, str] = {}
    for key, value in current.items():
        if key in os.environ and key not in previous_loaded:
            continue  # Explicitly set outside .env — don't overwrite
        current_value = os.environ.get(key)
        previous_value = previous_loaded.get(key)
        if current_value is None or current_value == previous_value:
            os.environ[key] = value
            loaded_values[key] = value

    _LOADED_DOTENV_VALUES = loaded_values


def _validate_sandstorm_config(raw: dict) -> dict:
    """Validate known sandstorm.json fields, drop invalid ones with warnings."""
    # Expected field types: field_name -> (allowed types tuple, human description)
    known_fields: dict[str, tuple[tuple[type, ...], str]] = {
        "system_prompt": ((str, dict), "str or dict"),
        "system_prompt_append": ((str,), "str"),
        "model": ((str,), "str"),
        "max_turns": ((int,), "int"),
        "output_format": ((dict,), "dict"),
        "agents": ((dict, list), "dict or list"),
        "mcp_servers": ((dict,), "dict"),
        "skills_dir": ((str,), "str"),
        "allowed_tools": ((list,), "list"),
        "webhook_url": ((str,), "str"),
        "timeout": ((int,), "int"),
        "template_skills": ((bool,), "bool"),
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

    if "max_turns" in validated and validated["max_turns"] < 1:
        logger.warning("sandstorm.json: max_turns must be >= 1 — skipping")
        del validated["max_turns"]

    if "timeout" in validated and not 5 <= validated["timeout"] <= 3600:
        logger.warning("sandstorm.json: timeout must be between 5 and 3600 — skipping")
        del validated["timeout"]

    if "model" in validated and not validated["model"].strip():
        logger.warning("sandstorm.json: model must be a non-empty string — skipping")
        del validated["model"]

    return validated


def _first_defined(*values: Any) -> Any:
    """Return the first value that is not None."""
    for value in values:
        if value is not None:
            return value
    return None


def _resolve_mcp_placeholders(value: Any, server_name: str) -> Any:
    """Resolve ${VAR} and ${VAR:-default} placeholders inside MCP config values."""
    if isinstance(value, dict):
        return {key: _resolve_mcp_placeholders(item, server_name) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_mcp_placeholders(item, server_name) for item in value]
    if not isinstance(value, str):
        return value

    def replace(match: re.Match[str]) -> str:
        name = match.group("name")
        default = match.group("default")
        resolved = os.environ.get(name)
        if resolved is not None:
            return resolved
        if default is not None:
            return default
        raise ValueError(
            f"mcp_servers.{server_name} requires environment variable {name} to be set"
        )

    return _MCP_ENV_VAR_PATTERN.sub(replace, value)


def _resolve_mcp_servers(mcp_servers: dict[str, Any] | None) -> dict[str, Any] | None:
    """Resolve env placeholders in effective MCP server definitions."""
    if mcp_servers is None:
        return None
    return {
        server_name: _resolve_mcp_placeholders(server_config, server_name)
        for server_name, server_config in mcp_servers.items()
    }


def load_sandstorm_config() -> dict | None:
    """Load sandstorm.json from the project root if it exists.

    Uses mtime-based caching to avoid re-reading disk on every call.
    """
    global _config_cache, _config_mtime

    config_path = _get_config_path()
    if not config_path.exists():
        _config_cache = None
        _config_mtime = 0.0
        return None

    try:
        mtime = config_path.stat().st_mtime
    except OSError:
        return _config_cache

    if _config_cache is not None and mtime == _config_mtime:
        return _config_cache

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("sandstorm.json: failed to read — %s", exc)
        return None

    if not isinstance(raw, dict):
        logger.error("sandstorm.json: expected a JSON object, got %s", type(raw).__name__)
        return None

    _config_cache = _validate_sandstorm_config(raw)
    _config_mtime = mtime
    return _config_cache


def _build_agent_config(
    request: QueryRequest,
    sandstorm_config: dict,
    disk_skills: dict[str, dict[str, str]],
) -> tuple[dict, dict[str, dict[str, str]]]:
    """Build agent_config dict and merged_skills from config + request overrides.

    Returns (agent_config, merged_skills) so the caller can upload skills
    and write agent_config.json into the sandbox.
    """
    merged_skills = dict(disk_skills)

    # Merge extra skills first (wrap inline content as SKILL.md), then apply whitelist.
    # Note: template_skills are baked into the sandbox image and always present
    # regardless of this whitelist — only disk_skills and extra_skills are filtered.
    if request.extra_skills:
        for name, content in request.extra_skills.items():
            merged_skills[name] = {"SKILL.md": content}
    if request.allowed_skills is not None:
        allowed = set(request.allowed_skills)
        merged_skills = {k: v for k, v in merged_skills.items() if k in allowed}

    has_skills = bool(merged_skills) or sandstorm_config.get("template_skills", False)

    # Apply MCP servers whitelist
    mcp_servers = sandstorm_config.get("mcp_servers")
    if mcp_servers is not None and request.allowed_mcp_servers is not None:
        allowed = set(request.allowed_mcp_servers)
        mcp_servers = {k: v for k, v in mcp_servers.items() if k in allowed}
    _refresh_project_dotenv()
    mcp_servers = _resolve_mcp_servers(mcp_servers)

    # Merge extra agents first, then apply whitelist to combined result
    agents_config = sandstorm_config.get("agents")
    if isinstance(agents_config, list) and (
        request.extra_agents or request.allowed_agents is not None
    ):
        raise ValueError(
            "extra_agents and allowed_agents require agents to be a dict"
            " in sandstorm.json, got list"
        )
    if request.extra_agents:
        agents_config = dict(agents_config) if agents_config is not None else {}
        agents_config.update(request.extra_agents)
    agents_whitelist = request.allowed_agents  # None = use all, [] = use none
    if isinstance(agents_config, dict) and agents_whitelist is not None:
        allowed = set(agents_whitelist)
        agents_config = {k: v for k, v in agents_config.items() if k in allowed}

    # Request-level allowed_tools overrides sandstorm.json
    allowed_tools_from_request = request.allowed_tools is not None
    allowed_tools = (
        request.allowed_tools
        if allowed_tools_from_request
        else sandstorm_config.get("allowed_tools")
    )
    # Auto-add "Skill" only for config-sourced allowed_tools (not explicit request override)
    if (
        allowed_tools is not None
        and has_skills
        and not allowed_tools_from_request
        and "Skill" not in allowed_tools
    ):
        allowed_tools = [*allowed_tools, "Skill"]

    # Build system prompt, then apply append from config if set
    sys_prompt = sandstorm_config.get("system_prompt")
    env_append = sandstorm_config.get("system_prompt_append")
    if env_append and sys_prompt:
        if isinstance(sys_prompt, dict) and "append" in sys_prompt:
            sys_prompt = {**sys_prompt, "append": sys_prompt["append"] + "\n\n" + env_append}
        elif isinstance(sys_prompt, dict):
            sys_prompt = {**sys_prompt, "append": env_append}
        elif isinstance(sys_prompt, str):
            sys_prompt = sys_prompt + "\n\n" + env_append
    elif env_append and not sys_prompt:
        sys_prompt = env_append

    timeout = _first_defined(request.timeout, sandstorm_config.get("timeout"), 300)

    agent_config = {
        "prompt": request.prompt,
        "cwd": "/home/user",
        "model": _first_defined(request.model, sandstorm_config.get("model")),
        "max_turns": _first_defined(request.max_turns, sandstorm_config.get("max_turns")),
        "system_prompt": sys_prompt,
        "output_format": (
            request.output_format
            if request.output_format is not None
            else sandstorm_config.get("output_format")
        )
        or None,  # empty dict = explicitly disabled
        "agents": agents_config,
        "mcp_servers": mcp_servers,
        "has_skills": has_skills,
        "allowed_tools": allowed_tools,
        "timeout": timeout,
    }

    return agent_config, merged_skills
