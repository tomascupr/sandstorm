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
            "args": ["-y", "@modelcontextprotocol/server-linear"],
            "env": {"LINEAR_API_KEY": "${LINEAR_API_KEY}"},
        },
        allowed_tools=("mcp__linear__*",),
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
