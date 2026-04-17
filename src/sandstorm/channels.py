"""Per-channel agent overlay resolution.

A channel in sandstorm.json's `channels` block can set a default starter,
model, and allowed_tools that apply to @mentions and DMs in that channel,
removing the need for per-mention `/model` overrides.

Merge order in callers: explicit request override > channel overlay >
project-level sandstorm.json defaults.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

logger = logging.getLogger(__name__)

# Keys a channel overlay can set. Anything else is ignored at validation time.
_CHANNEL_OVERLAY_KEYS = frozenset({"starter", "model", "allowed_tools"})


def resolve_channel_config(
    sandstorm_config: Mapping[str, object] | None, channel_id: str | None
) -> dict | None:
    """Return the overlay dict for `channel_id`, or None if no overlay is set.

    The returned dict only contains keys from `_CHANNEL_OVERLAY_KEYS`; other
    keys in the user's config are silently dropped so typos don't silently
    override things the caller didn't expect.
    """
    if not sandstorm_config or not channel_id:
        return None
    channels = sandstorm_config.get("channels")
    if not isinstance(channels, Mapping):
        return None
    overlay = channels.get(channel_id)
    if not isinstance(overlay, Mapping):
        return None
    filtered = {k: v for k, v in overlay.items() if k in _CHANNEL_OVERLAY_KEYS}
    return filtered or None


def validate_channels_section(value: object) -> dict | None:
    """Validate the `channels` section of sandstorm.json.

    Returns the validated dict (with invalid entries dropped + warnings
    logged) or None when the input is not a dict or is empty after
    filtering.
    """
    if not isinstance(value, dict):
        logger.warning("sandstorm.json 'channels' must be a dict — ignoring")
        return None
    out: dict = {}
    for channel_id, overlay in value.items():
        if not isinstance(channel_id, str) or not channel_id:
            logger.warning("channels entry with non-string key ignored")
            continue
        if not isinstance(overlay, dict):
            logger.warning("channels[%s] must be an object — ignoring", channel_id)
            continue
        filtered = {k: v for k, v in overlay.items() if k in _CHANNEL_OVERLAY_KEYS}
        unknown = set(overlay) - _CHANNEL_OVERLAY_KEYS
        if unknown:
            logger.warning(
                "channels[%s]: unknown keys dropped: %s",
                channel_id,
                ", ".join(sorted(unknown)),
            )
        if "starter" in filtered and not isinstance(filtered["starter"], str):
            logger.warning(
                "channels[%s].starter must be a string — ignoring overlay",
                channel_id,
            )
            continue
        if "model" in filtered and not isinstance(filtered["model"], str):
            logger.warning(
                "channels[%s].model must be a string — ignoring overlay",
                channel_id,
            )
            continue
        if "allowed_tools" in filtered and not (
            isinstance(filtered["allowed_tools"], list)
            and all(isinstance(t, str) for t in filtered["allowed_tools"])
        ):
            logger.warning(
                "channels[%s].allowed_tools must be a list of strings — ignoring overlay",
                channel_id,
            )
            continue
        if filtered:
            out[channel_id] = filtered
    return out or None
