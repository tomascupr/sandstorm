"""Bundled toolpack definitions for ``ds add``."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, cast


def _freeze_toolpack_value(value: Any) -> Any:
    """Recursively freeze canonical toolpack config values."""
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_toolpack_value(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_toolpack_value(item) for item in value)
    return value


def _thaw_toolpack_value(value: Any) -> Any:
    """Return a mutable copy of a frozen toolpack config value."""
    if isinstance(value, Mapping):
        return {key: _thaw_toolpack_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_toolpack_value(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class ToolpackDefinition:
    slug: str
    title: str
    description: str
    required_env_vars: tuple[str, ...]
    mcp_server_name: str
    mcp_server_config: Mapping[str, Any]
    allowed_tools: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "mcp_server_config",
            _freeze_toolpack_value(self.mcp_server_config),
        )


TOOLPACKS: tuple[ToolpackDefinition, ...] = (
    ToolpackDefinition(
        slug="linear",
        title="Linear",
        description="Connect Linear via MCP for issue lookup, search, and updates.",
        required_env_vars=("LINEAR_API_KEY",),
        mcp_server_name="linear",
        mcp_server_config={
            "command": "npx",
            "args": ["-y", "linear-mcp"],
            # linear-mcp expects LINEAR_ACCESS_TOKEN; map from LINEAR_API_KEY
            # to avoid breaking existing .env files from the old server package.
            "env": {"LINEAR_ACCESS_TOKEN": "${LINEAR_API_KEY}"},
        },
        allowed_tools=("mcp__linear__*",),
    ),
    ToolpackDefinition(
        slug="notion",
        title="Notion",
        description="Read and search Notion pages, databases, and data sources.",
        required_env_vars=("NOTION_TOKEN",),
        mcp_server_name="notion",
        mcp_server_config={
            "command": "npx",
            "args": ["-y", "@notionhq/notion-mcp-server"],
            "env": {"NOTION_TOKEN": "${NOTION_TOKEN}"},
        },
        allowed_tools=("mcp__notion__*",),
    ),
    ToolpackDefinition(
        slug="firecrawl",
        title="Firecrawl",
        description="Scrape, crawl, and extract structured data from websites.",
        required_env_vars=("FIRECRAWL_API_KEY",),
        mcp_server_name="firecrawl",
        mcp_server_config={
            "command": "npx",
            "args": ["-y", "firecrawl-mcp"],
            "env": {"FIRECRAWL_API_KEY": "${FIRECRAWL_API_KEY}"},
        },
        allowed_tools=("mcp__firecrawl__*",),
    ),
    ToolpackDefinition(
        slug="exa",
        title="Exa",
        description="AI-powered web search, code search, and company research.",
        required_env_vars=("EXA_API_KEY",),
        mcp_server_name="exa",
        mcp_server_config={
            "command": "npx",
            "args": ["-y", "exa-mcp-server"],
            "env": {"EXA_API_KEY": "${EXA_API_KEY}"},
        },
        allowed_tools=("mcp__exa__*",),
    ),
    ToolpackDefinition(
        slug="github",
        title="GitHub",
        description="Search repos, code, issues, and pull requests on GitHub.",
        required_env_vars=("GITHUB_TOKEN",),
        mcp_server_name="github",
        mcp_server_config={
            "command": "npx",
            "args": ["-y", "@fre4x/github"],
            "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"},
        },
        allowed_tools=("mcp__github__*",),
    ),
)

_TOOLPACK_BY_SLUG = {toolpack.slug: toolpack for toolpack in TOOLPACKS}


def list_toolpacks() -> tuple[ToolpackDefinition, ...]:
    """Return bundled toolpacks in display order."""
    return TOOLPACKS


def resolve_toolpack(name: str) -> ToolpackDefinition:
    """Resolve a toolpack slug into its canonical definition."""
    normalized = name.strip().lower()
    try:
        return _TOOLPACK_BY_SLUG[normalized]
    except KeyError as exc:
        choices = ", ".join(toolpack.slug for toolpack in TOOLPACKS)
        raise ValueError(f"Unknown toolpack {name!r}. Choose one of: {choices}") from exc


def clone_mcp_server_config(toolpack: ToolpackDefinition) -> dict[str, Any]:
    """Return a deep copy of the toolpack's canonical MCP server config."""
    return cast(dict[str, Any], _thaw_toolpack_value(toolpack.mcp_server_config))
