"""Sandstorm's Slack App Home tab.

Read-first layout with two write actions (Forget memory, Cancel run).
Anything heavier — editing channels, triggers, models — stays in
sandstorm.json for v0.9.1. The tab gives users visibility into their
personal memories, any in-flight run, and what the bot is set to do
in their channels.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from .cancellation import is_registered
from .config import load_sandstorm_config
from .memory import memory_store
from .store import run_store

logger = logging.getLogger(__name__)


def _status_block(tenant: str | None) -> dict:
    """Top-of-home status: most-recent run metadata for the user's tenant."""
    most_recent = run_store.find_most_recent(lambda r: r.team_id == tenant)
    if most_recent is None:
        text = "*No Sandstorm runs yet in this workspace.*"
    else:
        cost = f"${most_recent.cost_usd:.4f}" if most_recent.cost_usd is not None else "n/a"
        duration = (
            f"{most_recent.duration_secs:.1f}s" if most_recent.duration_secs is not None else "n/a"
        )
        text = (
            f"*Most recent run*: `{most_recent.id}` ({most_recent.status})  |  "
            f"model: `{most_recent.model or 'default'}`  |  "
            f"cost: {cost}  |  duration: {duration}"
        )
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _channel_defaults_blocks(
    sandstorm_config: Mapping[str, object] | None,
) -> list[dict]:
    """Render the per-channel default agent overlay (read-only)."""
    channels = sandstorm_config.get("channels") if isinstance(sandstorm_config, Mapping) else None
    if not isinstance(channels, Mapping) or not channels:
        return []
    lines = []
    for channel_id, overlay in sorted(channels.items()):
        if not isinstance(overlay, Mapping):
            continue
        starter = overlay.get("starter", "default")
        model = overlay.get("model", "default")
        lines.append(f"• <#{channel_id}> → starter `{starter}`, model `{model}`")
    if not lines:
        return []
    return [
        {"type": "header", "text": {"type": "plain_text", "text": "Channel defaults"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
    ]


def _memory_blocks(team_id: str | None, user_id: str | None) -> list[dict]:
    """Render the user's personal memories with per-item Forget buttons."""
    personal = memory_store.list(team_id, user_id, scope="user")
    team_scope = memory_store.list(team_id, user_id, scope="team")

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": "Memory"}},
    ]

    if personal:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Your memories*"}})
        for memory in personal:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"• {memory.text}",
                    },
                    "accessory": {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Forget"},
                        "style": "danger",
                        "action_id": "sandstorm_forget_memory",
                        "value": memory.id,
                    },
                }
            )
    else:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "_No personal memories yet._ Use `/remember <fact>` in any channel.",
                },
            }
        )

    if team_scope:
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": "*Team memories* (read-only)"}}
        )
        lines = "\n".join(f"• {m.text}" for m in team_scope)
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": lines}})

    return blocks


def _active_run_blocks(tenant: str | None, user_id: str | None) -> list[dict]:
    """Render a Cancel button for the user's current in-flight run, if any."""
    active = run_store.find_most_recent(
        lambda r: r.team_id == tenant and r.user_id == user_id and r.status == "running"
    )
    if active is None:
        return []
    if not is_registered(active.id):
        return []
    return [
        {"type": "header", "text": {"type": "plain_text", "text": "Active run"}},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"`{active.id}` — {active.prompt}"
                    f"\n<{'https://sandstorm/' + active.id}|view dashboard>"
                ),
            },
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "Cancel"},
                "style": "danger",
                "action_id": "sandstorm_cancel_run",
                "value": active.id,
            },
        },
    ]


def _triggers_blocks(sandstorm_config: Mapping[str, object] | None) -> list[dict]:
    """Render active triggers (read-only in v0.9.1)."""
    from .triggers import load_triggers

    if not sandstorm_config:
        return []
    try:
        triggers = load_triggers(sandstorm_config)
    except ValueError:
        return []
    if not triggers:
        return []
    lines = []
    for t in triggers:
        if t.type == "cron":
            lines.append(f"• `{t.name}` (cron `{t.schedule}`)")
        elif t.type == "webhook":
            secret = "secret-required" if t.secret else "OPEN"
            lines.append(f"• `{t.name}` (webhook `{t.path}` · {secret})")
        else:
            ch = ", ".join(t.channels) or "any channel"
            lines.append(f"• `{t.name}` (`:{t.emoji}:` in {ch})")
    return [
        {"type": "header", "text": {"type": "plain_text", "text": "Triggers"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
    ]


def build_home_view(
    *,
    team_id: str | None,
    user_id: str | None,
) -> dict:
    """Assemble the full Home view payload for views_publish."""
    config = load_sandstorm_config()
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Sandstorm"},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Claude Agent SDK, or any LLM, in your Slack on your infra.",
                },
            ],
        },
        _status_block(team_id),
    ]
    blocks.extend(_active_run_blocks(team_id, user_id))
    blocks.extend(_channel_defaults_blocks(config))
    blocks.extend(_memory_blocks(team_id, user_id))
    blocks.extend(_triggers_blocks(config))
    return {"type": "home", "blocks": blocks}


async def publish_home_view(client, *, user_id: str, team_id: str | None) -> None:
    """Publish the Home tab for `user_id`. Logs + swallows errors so event
    handling doesn't crash when App Home is misconfigured."""
    try:
        view = build_home_view(team_id=team_id, user_id=user_id)
        await client.views_publish(user_id=user_id, view=view)
    except Exception:
        logger.exception("Failed to publish App Home view for %s", user_id)
