"""Starter catalog and scaffold helpers for ``ds init``."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from importlib.resources import files as pkg_files
from importlib.resources.abc import Traversable
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StarterDefinition:
    slug: str
    title: str
    description: str
    next_step_command: str
    aliases: tuple[str, ...] = ()


STARTERS: tuple[StarterDefinition, ...] = (
    StarterDefinition(
        slug="general-assistant",
        title="General Assistant",
        description=(
            "General-purpose agent for research, documents, support, ops, and software work."
        ),
        next_step_command='ds "Compare Notion, Coda, and Slite for async product teams"',
    ),
    StarterDefinition(
        slug="research-brief",
        title="Research Brief",
        description="Research a topic, compare options, and return a concise decision brief.",
        next_step_command='ds "Compare Linear, Jira, and Asana for a 50-person product org"',
        aliases=("competitive-analysis",),
    ),
    StarterDefinition(
        slug="document-analyst",
        title="Document Analyst",
        description=(
            "Analyze transcripts, reports, PDFs, or decks and extract decisions and risks."
        ),
        next_step_command=(
            'ds "Summarize this transcript and extract risks plus next steps" '
            "-f /path/to/transcript.txt"
        ),
    ),
    StarterDefinition(
        slug="support-triage",
        title="Support Triage",
        description="Triage tickets or issue exports into priorities, owners, and next actions.",
        next_step_command=(
            'ds "Triage these incoming tickets for urgency and next action" '
            "-f /path/to/tickets.json"
        ),
        aliases=("issue-triage",),
    ),
    StarterDefinition(
        slug="api-extractor",
        title="API Extractor",
        description="Crawl documentation and draft an API summary plus OpenAPI starter spec.",
        next_step_command=(
            'ds "Turn the docs at https://docs.stripe.com/api/subscriptions into a draft '
            'OpenAPI spec"'
        ),
        aliases=("docs-to-openapi",),
    ),
    StarterDefinition(
        slug="security-audit",
        title="Security Audit",
        description="Run a structured security audit with sub-agents and an OWASP skill.",
        next_step_command=(
            'ds "Run a security audit on this codebase" '
            "-f /path/to/requirements.txt -f /path/to/src/auth.py"
        ),
    ),
)

_STARTER_BY_SLUG = {starter.slug: starter for starter in STARTERS}
_ALIAS_TO_SLUG = {alias: starter.slug for starter in STARTERS for alias in starter.aliases}


def list_starters() -> tuple[StarterDefinition, ...]:
    """Return the canonical starter catalog in display order."""
    return STARTERS


def resolve_starter(name: str) -> StarterDefinition:
    """Resolve a starter slug or alias into its canonical definition."""
    normalized = name.strip().lower()
    slug = _ALIAS_TO_SLUG.get(normalized, normalized)
    try:
        return _STARTER_BY_SLUG[slug]
    except KeyError as exc:
        choices = ", ".join(starter.slug for starter in STARTERS)
        raise ValueError(f"Unknown starter {name!r}. Choose one of: {choices}") from exc


def scaffold_files(
    starter: StarterDefinition, focus_sentence: str | None = None
) -> dict[str, str]:
    """Return scaffold output files for a starter."""
    files: dict[str, str] = {
        ".env.example": _read_text_resource("sandstorm.starters", "_shared/env.example"),
    }
    starter_root = pkg_files("sandstorm.starters").joinpath(starter.slug)
    for relative_path, content in _iter_text_files(starter_root, Path()):
        output_path = _map_resource_path(relative_path)
        if output_path == "sandstorm.json":
            content = _apply_focus_sentence(starter.slug, content, focus_sentence)
        files[output_path] = content
    return files


def _read_text_resource(package: str, resource_path: str) -> str:
    return pkg_files(package).joinpath(resource_path).read_text(encoding="utf-8")


def _iter_text_files(root: Traversable, relative: Path) -> Iterator[tuple[str, str]]:
    for entry in sorted(root.iterdir(), key=lambda item: item.name):
        next_relative = relative / entry.name
        if entry.is_dir():
            yield from _iter_text_files(entry, next_relative)
        elif entry.is_file():
            try:
                yield next_relative.as_posix(), entry.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError(
                    f"Starter asset {next_relative.as_posix()} is not valid UTF-8"
                ) from exc


def _map_resource_path(relative_path: str) -> str:
    if relative_path.startswith("claude-skills/"):
        return relative_path.replace("claude-skills/", ".claude/skills/", 1)
    return relative_path


def _apply_focus_sentence(
    starter_slug: str, sandstorm_json: str, focus_sentence: str | None
) -> str:
    focus = (focus_sentence or "").strip()
    if not focus:
        return sandstorm_json

    try:
        config = json.loads(sandstorm_json)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON in starter {starter_slug!r} sandstorm.json: {exc}"
        ) from exc
    config["system_prompt_append"] = focus
    return json.dumps(config, indent=2) + "\n"
