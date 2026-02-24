"""Sandstorm configuration loading, validation, and agent config building."""

import json
import logging
from pathlib import Path

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
    # Model name overrides (remap SDK aliases to provider model IDs)
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    # MCP server credentials
    "LINEAR_API_KEY",
]

# ── mtime-based config cache ──────────────────────────────────────────────────

_config_cache: dict | None = None
_config_mtime: float = 0.0


def _get_config_path() -> Path:
    """Resolve sandstorm.json from the current working directory."""
    return Path.cwd() / "sandstorm.json"


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

    return validated


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
        raw = json.loads(config_path.read_text())
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

    timeout = request.timeout or sandstorm_config.get("timeout") or 300

    agent_config = {
        "prompt": request.prompt,
        "cwd": "/home/user",
        "model": request.model or sandstorm_config.get("model"),
        "max_turns": request.max_turns or sandstorm_config.get("max_turns"),
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
