"""Google Chat App Home — Cards v2 rendering."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from .cancellation import is_registered
from .config import load_sandstorm_config
from .memory import memory_store
from .store import run_store

logger = logging.getLogger(__name__)


def _status_section(tenant: str | None, user_id: str | None) -> dict:
    most_recent = run_store.find_most_recent(
        lambda r: r.team_id == tenant and r.user_id == user_id
    )
    if most_recent is None:
        text = "No Sandstorm runs yet."
    else:
        cost = f"${most_recent.cost_usd:.4f}" if most_recent.cost_usd is not None else "n/a"
        duration = (
            f"{most_recent.duration_secs:.1f}s" if most_recent.duration_secs is not None else "n/a"
        )
        text = (
            f"Most recent run: {most_recent.id} ({most_recent.status}) | "
            f"model: {most_recent.model or 'default'} | "
            f"cost: {cost} | duration: {duration}"
        )
    return {"widgets": [{"textParagraph": {"text": text}}]}


def _active_run_section(tenant: str | None, user_id: str | None) -> dict | None:
    active = run_store.find_most_recent(
        lambda r: r.team_id == tenant and r.user_id == user_id and r.status == "running"
    )
    if active is None or not is_registered(active.id):
        return None
    return {
        "header": "Active run",
        "widgets": [
            {"textParagraph": {"text": f"{active.id} — {active.prompt}"}},
            {
                "buttonList": {
                    "buttons": [{
                        "text": "Cancel",
                        "color": {"red": 0.8, "green": 0.1, "blue": 0.1, "alpha": 1},
                        "onClick": {
                            "action": {
                                "actionMethodName": "sandstorm_cancel_run",
                                "parameters": [{"key": "run_id", "value": active.id}],
                            }
                        },
                    }]
                }
            },
        ],
    }


def _memory_section(team_id: str | None, user_id: str | None) -> dict:
    personal = memory_store.list(team_id, user_id, scope="user")
    team_scope = memory_store.list(team_id, user_id, scope="team")

    widgets: list[dict] = []

    if personal:
        widgets.append({"textParagraph": {"text": "<b>Your memories</b>"}})
        for mem in personal:
            widgets.append({
                "decoratedText": {
                    "text": mem.text,
                    "button": {
                        "text": "Forget",
                        "color": {"red": 0.8, "green": 0.1, "blue": 0.1, "alpha": 1},
                        "onClick": {
                            "action": {
                                "actionMethodName": "sandstorm_forget_memory",
                                "parameters": [{"key": "memory_id", "value": mem.id}],
                            }
                        },
                    },
                }
            })
    else:
        widgets.append({
            "textParagraph": {"text": "No personal memories yet. Use /remember in any space."}
        })

    if team_scope:
        widgets.append({"textParagraph": {"text": "<b>Team memories</b> (read-only)"}})
        for mem in team_scope:
            widgets.append({"textParagraph": {"text": f"• {mem.text}"}})

    return {"header": "Memory", "widgets": widgets}


def _channel_defaults_section(
    sandstorm_config: Mapping[str, object] | None,
) -> dict | None:
    channels = sandstorm_config.get("channels") if isinstance(sandstorm_config, Mapping) else None
    if not isinstance(channels, Mapping) or not channels:
        return None
    lines = []
    for channel_id, overlay in sorted(channels.items()):
        if not isinstance(overlay, Mapping):
            continue
        starter = overlay.get("starter", "default")
        model = overlay.get("model", "default")
        lines.append(f"• {channel_id} → starter: {starter}, model: {model}")
    if not lines:
        return None
    return {
        "header": "Space defaults",
        "widgets": [{"textParagraph": {"text": "\n".join(lines)}}],
    }


def _triggers_section(sandstorm_config: Mapping[str, object] | None) -> dict | None:
    from .triggers import load_triggers

    if not sandstorm_config:
        return None
    try:
        triggers = load_triggers(sandstorm_config)
    except ValueError:
        return None
    if not triggers:
        return None
    lines = []
    for t in triggers:
        if t.type == "cron":
            lines.append(f"• {t.name} (cron: {t.schedule})")
        elif t.type == "webhook":
            secret = "secret-required" if t.secret else "OPEN"
            lines.append(f"• {t.name} (webhook: {t.path} · {secret})")
        else:
            ch = ", ".join(t.channels) or "any space"
            lines.append(f"• {t.name} (:{t.emoji}: in {ch})")
    return {
        "header": "Triggers",
        "widgets": [{"textParagraph": {"text": "\n".join(lines)}}],
    }


def build_home_card(*, team_id: str | None, user_id: str | None) -> dict:
    """Build the App Home card (Cards v2 format)."""
    config = load_sandstorm_config()
    sections = [_status_section(team_id, user_id)]

    active_run = _active_run_section(team_id, user_id)
    if active_run:
        sections.append(active_run)

    channel_defaults = _channel_defaults_section(config)
    if channel_defaults:
        sections.append(channel_defaults)

    sections.append(_memory_section(team_id, user_id))

    triggers = _triggers_section(config)
    if triggers:
        sections.append(triggers)

    return {
        "cardId": "sandstorm_home",
        "card": {
            "header": {
                "title": "Sandstorm",
                "subtitle": "AI agents in secure sandboxes",
            },
            "sections": sections,
        },
    }
