"""Trigger primitives: cron + inbound webhooks for agent runs.

Positioning: Managed Agents has webhook callbacks on session.status_idled
but no scheduler; Claude Code Routines has a 1-hour minimum cron. This
module ships sub-hourly cron and generic webhook triggers so Sandstorm
fills the scheduler gap and composes with MA's session model.

No durable queue in v0.9.1: cron runs missed while the server is down
are not replayed, and webhook triggers are fire-and-forget. Durability
lands in v0.10 once the shape is validated in the wild.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

logger = logging.getLogger(__name__)

TriggerType = Literal["cron", "webhook", "reaction"]

_SLUG_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
_PATH_PATTERN = re.compile(r"^/[A-Za-z0-9_\-./]{1,120}$")
# Dotted placeholder with safe lookup path. Whitespace inside braces is OK.
_TEMPLATE_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_-]+)*)\s*\}\}")


@dataclass(frozen=True, slots=True)
class TriggerDefinition:
    name: str
    type: TriggerType
    prompt: str
    # Cron-specific
    schedule: str | None = None
    # Webhook-specific
    path: str | None = None
    secret: str | None = None
    # Reaction-specific (Slack)
    emoji: str | None = None
    channels: tuple[str, ...] = ()


def load_triggers(sandstorm_config: Mapping[str, object]) -> list[TriggerDefinition]:
    """Parse + validate the `triggers` section of sandstorm.json.

    Raises ValueError on any shape problem; callers are expected to surface
    the error to the operator at startup, not to continue with a partial set.
    """
    raw = sandstorm_config.get("triggers")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("sandstorm.json 'triggers' must be a list")

    from croniter import croniter  # lazy import keeps the module import cheap

    seen_names: set[str] = set()
    seen_paths: set[str] = set()
    seen_reactions: set[tuple[str, str]] = set()
    triggers: list[TriggerDefinition] = []

    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(f"triggers[{index}] must be an object")
        name = entry.get("name")
        ttype = entry.get("type")
        prompt = entry.get("prompt")
        if not isinstance(name, str) or not _SLUG_PATTERN.match(name):
            raise ValueError(f"triggers[{index}] name must match {_SLUG_PATTERN.pattern}")
        if ttype not in ("cron", "webhook", "reaction"):
            raise ValueError(f"trigger {name!r} type must be cron / webhook / reaction")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"trigger {name!r} must have a non-empty prompt")
        if name in seen_names:
            raise ValueError(f"duplicate trigger name: {name!r}")
        seen_names.add(name)

        if ttype == "cron":
            schedule = entry.get("schedule")
            if not isinstance(schedule, str) or not croniter.is_valid(schedule):
                raise ValueError(f"trigger {name!r} has invalid cron schedule: {schedule!r}")
            triggers.append(
                TriggerDefinition(name=name, type="cron", prompt=prompt, schedule=schedule)
            )
        elif ttype == "webhook":
            path = entry.get("path")
            if not isinstance(path, str) or not _PATH_PATTERN.match(path):
                raise ValueError(
                    f"trigger {name!r} path must start with / and match {_PATH_PATTERN.pattern}"
                )
            if path in seen_paths:
                raise ValueError(f"duplicate webhook path: {path!r}")
            seen_paths.add(path)
            secret = entry.get("secret")
            if secret is not None and not isinstance(secret, str):
                raise ValueError(f"trigger {name!r} secret must be a string")
            if not secret:
                logger.warning(
                    "Webhook trigger %r has no `secret` — do not expose its "
                    "endpoint to the public internet without auth.",
                    name,
                )
            triggers.append(
                TriggerDefinition(
                    name=name,
                    type="webhook",
                    prompt=prompt,
                    path=path,
                    secret=secret or None,
                )
            )
        else:  # reaction
            emoji = entry.get("emoji")
            channels = entry.get("channels")
            if not isinstance(emoji, str) or not emoji.strip():
                raise ValueError(
                    f"trigger {name!r} must specify a non-empty `emoji` "
                    "(Slack shortcode, without colons)"
                )
            if channels is None:
                channels_tuple: tuple[str, ...] = ()
            elif isinstance(channels, list) and all(isinstance(c, str) for c in channels):
                channels_tuple = tuple(channels)
            else:
                raise ValueError(
                    f"trigger {name!r} `channels` must be a list of strings or omitted"
                )
            for channel_id in channels_tuple or ("*",):
                key = (emoji, channel_id)
                if key in seen_reactions:
                    raise ValueError(
                        f"reaction trigger :{emoji}: in {channel_id} is defined twice"
                    )
                seen_reactions.add(key)
            triggers.append(
                TriggerDefinition(
                    name=name,
                    type="reaction",
                    prompt=prompt,
                    emoji=emoji,
                    channels=channels_tuple,
                )
            )

    return triggers


def render_prompt(
    template: str,
    *,
    body: Mapping[str, object] | None = None,
    headers: Mapping[str, object] | None = None,
    message: Mapping[str, object] | None = None,
    channel: Mapping[str, object] | None = None,
    reaction: str | None = None,
) -> str:
    """Substitute `{{body.foo.bar}}` / `{{headers.x-foo}}` / `{{message.text}}`
    / `{{channel.id}}` / `{{reaction}}` placeholders.

    No Jinja, no eval. Missing keys render as empty string (intentional: lets a
    single prompt template survive missing optional fields).
    """
    sources: dict[str, object] = {}
    if body is not None:
        sources["body"] = body
    if headers is not None:
        sources["headers"] = headers
    if message is not None:
        sources["message"] = message
    if channel is not None:
        sources["channel"] = channel
    if reaction is not None:
        sources["reaction"] = reaction

    def replace(match: re.Match[str]) -> str:
        path = match.group(1)
        parts = path.split(".")
        root = sources.get(parts[0])
        if root is None:
            return ""
        # For single-key lookups on scalar roots (e.g. {{reaction}})
        if len(parts) == 1:
            return str(root) if not isinstance(root, Mapping) else ""
        cursor: object = root
        for segment in parts[1:]:
            if isinstance(cursor, Mapping):
                cursor = cursor.get(segment)
            else:
                return ""
            if cursor is None:
                return ""
        return str(cursor)

    return _TEMPLATE_PATTERN.sub(replace, template)


def verify_webhook_secret(expected: str | None, received: str | None) -> bool:
    """Constant-time comparison of a webhook secret header.

    Returns True when no secret is configured (open endpoint, warning logged
    at load time) or when the header exactly matches the configured secret.
    """
    if not expected:
        return True
    if not received:
        return False
    return hmac.compare_digest(expected, received)


async def start_cron_scheduler(
    triggers: list[TriggerDefinition],
    fire: Callable[[TriggerDefinition], Awaitable[None]],
) -> asyncio.Task | None:
    """Start an asyncio task that fires cron triggers at their next instant.

    Returns the task so the caller can cancel it on shutdown. When there are
    no cron triggers, returns None (nothing to run).
    """
    cron_triggers = [t for t in triggers if t.type == "cron"]
    if not cron_triggers:
        return None

    from croniter import croniter

    async def _loop() -> None:
        while True:
            now = datetime.now(UTC)
            # Compute the next fire instant for each cron trigger, pick the
            # earliest, sleep to it, fire all triggers due within a 1-second
            # tolerance (covers schedule coincidences and sub-second drift).
            next_times: list[tuple[datetime, TriggerDefinition]] = []
            for trigger in cron_triggers:
                nxt = croniter(trigger.schedule or "", now).get_next(datetime)
                # croniter returns naive datetimes when base is naive; we pass
                # UTC, so `get_next` returns tz-aware UTC.
                if nxt.tzinfo is None:
                    nxt = nxt.replace(tzinfo=UTC)
                next_times.append((nxt, trigger))
            next_times.sort(key=lambda pair: pair[0])
            earliest = next_times[0][0]
            sleep_seconds = max(0.0, (earliest - datetime.now(UTC)).total_seconds())
            try:
                await asyncio.sleep(sleep_seconds)
            except asyncio.CancelledError:
                logger.info("Cron scheduler cancelled")
                return
            due_cutoff = datetime.now(UTC)
            for fire_time, trigger in next_times:
                # 1-second tolerance for co-scheduled triggers
                if (fire_time - due_cutoff).total_seconds() > 1.0:
                    break
                try:
                    await fire(trigger)
                except Exception:
                    logger.exception("Cron trigger %r failed to fire", trigger.name)

    return asyncio.create_task(_loop(), name="sandstorm-cron-scheduler")
