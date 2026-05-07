"""Google Chat bot integration for Sandstorm."""

from __future__ import annotations

import asyncio
import logging
import time

from .memory import memory_store
from .platform import BINARY_MIME_PREFIXES, MAX_FILE_SIZE, unique_filename
from .store import run_store

logger = logging.getLogger(__name__)


def parse_event_type(body: dict) -> str:
    """Determine the event type from a Google Chat event payload."""
    event_type = body.get("type", "")

    if event_type == "ADDED_TO_SPACE":
        return "added_to_space"
    if event_type == "MESSAGE":
        message = body.get("message", {})
        if message.get("slashCommand"):
            return "slash_command"
        space_type = body.get("space", {}).get("type", "")
        if space_type == "DM":
            return "dm_message"
        return "mention"
    if event_type == "CARD_CLICKED":
        return "card_clicked"
    if event_type == "APP_HOME":
        return "app_home"
    if event_type == "REACTION_ADDED":
        return "reaction_added"
    return "unknown"


def build_metadata_cards(
    run_id: str,
    model: str | None,
    cost_usd: float | None,
    num_turns: int | None,
    duration_secs: float | None,
) -> list[dict]:
    """Build a Cards v2 footer with run metadata and feedback buttons."""
    parts: list[str] = []
    if model:
        parts.append(f"Model: {model}")
    if num_turns is not None:
        parts.append(f"Turns: {num_turns}")
    if cost_usd is not None:
        parts.append(f"Cost: ${cost_usd:.4f}")
    if duration_secs is not None:
        parts.append(f"Duration: {duration_secs:.1f}s")

    return [
        {
            "cardId": f"metadata_{run_id}",
            "card": {
                "sections": [
                    {
                        "widgets": [
                            {"textParagraph": {"text": " | ".join(parts)}}
                            if parts
                            else {},
                            {
                                "buttonList": {
                                    "buttons": [
                                        {
                                            "text": "\U0001f44d Helpful",
                                            "onClick": {
                                                "action": {
                                                    "actionMethodName": "sandstorm_feedback",
                                                    "parameters": [
                                                        {
                                                            "key": "run_id",
                                                            "value": run_id,
                                                        },
                                                        {
                                                            "key": "sentiment",
                                                            "value": "positive",
                                                        },
                                                    ],
                                                }
                                            },
                                        },
                                        {
                                            "text": "\U0001f44e Not helpful",
                                            "onClick": {
                                                "action": {
                                                    "actionMethodName": "sandstorm_feedback",
                                                    "parameters": [
                                                        {
                                                            "key": "run_id",
                                                            "value": run_id,
                                                        },
                                                        {
                                                            "key": "sentiment",
                                                            "value": "negative",
                                                        },
                                                    ],
                                                }
                                            },
                                        },
                                    ]
                                }
                            },
                        ]
                    }
                ]
            },
        }
    ]


def dispatch_slash_command(
    body: dict, *, team_id: str | None, user_id: str | None
) -> dict:
    """Route a Google Chat slash command by commandId to the appropriate handler."""
    command = body.get("message", {}).get("slashCommand", {})
    command_id = str(command.get("commandId", ""))
    text = body.get("message", {}).get("argumentText", "").strip()
    channel_id = body.get("space", {}).get("name", "")

    if command_id == "1":  # /remember
        if not text:
            return {"text": "Usage: `/remember <fact>`."}
        memory_store.remember(team_id, user_id, text, scope="user")
        return {"text": f"Remembered (user): _{text}_"}

    elif command_id == "2":  # /team_remember
        if not text:
            return {"text": "Usage: `/team_remember <fact>`."}
        memory_store.remember(team_id, user_id, text, scope="team")
        return {"text": f"Remembered (team): _{text}_"}

    elif command_id == "3":  # /channel_remember
        if not text:
            return {"text": "Usage: `/channel_remember <fact>`."}
        if not channel_id:
            return {"text": "Channel-scoped memory requires a space context."}
        memory_store.remember(
            team_id, user_id, text, scope="channel", channel_id=channel_id
        )
        return {"text": f"Remembered (channel): _{text}_"}

    elif command_id == "4":  # /forget
        if not text:
            return {"text": "Usage: `/forget <substring>`."}
        deleted = memory_store.forget(team_id, user_id, text, channel_id=channel_id)
        if deleted:
            return {
                "text": f"Forgot {deleted} memor{'y' if deleted == 1 else 'ies'}."
            }
        return {"text": f"No memory matched `{text}`."}

    elif command_id == "5":  # /memories
        memories = memory_store.list(team_id, user_id, channel_id=channel_id)
        if not memories:
            return {"text": "No memories yet. Use `/remember <fact>` to add one."}
        lines = [f"{i + 1}. [{m.scope}] {m.text}" for i, m in enumerate(memories)]
        return {"text": "Your memories:\n" + "\n".join(lines)}

    elif command_id == "6":  # /model
        return {"text": "Model override not yet implemented for Google Chat."}

    elif command_id == "7":  # /cancel
        from .cancellation import request_cancellation

        run = run_store.find_most_recent(
            lambda r: (
                r.team_id == team_id
                and r.user_id == user_id
                and r.status == "running"
            )
        )
        if run is None:
            return {"text": "You have no in-flight run to cancel."}
        if request_cancellation(run.id):
            return {"text": f"Cancelled run `{run.id}`."}
        return {"text": f"Run `{run.id}` is already finishing."}

    return {"text": "Unknown command."}

async def fetch_thread_messages(service, space_name: str, thread_key: str) -> list[dict]:
    """Fetch all messages in a Google Chat thread.

    Returns normalized message dicts: {user, text, files}
    """
    try:
        response = await asyncio.to_thread(
            service.spaces().messages().list(
                parent=space_name,
                filter=f'thread.name = "{thread_key}"',
            ).execute
        )
        raw_messages = response.get("messages", [])
        normalized = []
        for msg in raw_messages:
            sender = msg.get("sender", {})
            user = sender.get("name", "unknown")
            text = msg.get("text", "").strip()
            files = []
            for attachment in msg.get("attachment", []):
                data_ref = attachment.get("attachmentDataRef", {})
                files.append({
                    "name": attachment.get("name", "unknown"),
                    "mimetype": attachment.get("contentType", "application/octet-stream"),
                    "size": int(data_ref.get("length", 0)),
                    "resource_name": data_ref.get("resourceName", ""),
                })
            entry: dict = {"user": user, "text": text}
            if files:
                entry["files"] = files
            normalized.append(entry)
        return normalized
    except Exception:
        logger.warning("Failed to fetch thread messages", exc_info=True)
        return []


async def download_thread_files(
    service, messages: list[dict], bot_user_id: str
) -> tuple[dict[str, str], dict[str, bytes]]:
    """Download files from Google Chat thread messages.

    Returns (text_files, binary_files) matching the Slack function signature.
    """
    text_files: dict[str, str] = {}
    binary_files: dict[str, bytes] = {}
    seen: set[str] = set()

    for msg in messages:
        if msg.get("user") == bot_user_id:
            continue

        for f in msg.get("files", []):
            raw_name = f.get("name", "unknown")
            name = unique_filename(raw_name, seen)
            mimetype = f.get("mimetype", "")
            size = f.get("size", 0)
            is_binary = any(mimetype.startswith(prefix) for prefix in BINARY_MIME_PREFIXES)
            resource_name = f.get("resource_name", "")

            if size > MAX_FILE_SIZE:
                logger.warning("Skipping large file: %s (%d bytes)", name, size)
                continue

            if not resource_name:
                continue

            try:
                response = await asyncio.to_thread(
                    service.media().download(resourceName=resource_name).execute
                )
                if is_binary:
                    binary_files[name] = response
                else:
                    binary_files[name] = response  # treat unknown as binary
                    # Try to decode as text
                    try:
                        text_files[name] = response.decode("utf-8")
                        del binary_files[name]
                    except (UnicodeDecodeError, AttributeError):
                        pass
            except Exception:
                logger.warning("Failed to download file: %s", name, exc_info=True)

    return text_files, binary_files


FLUSH_INTERVAL = 2.0


class GChatStreamer:
    """Buffers text chunks, updates the Google Chat message every ~2 seconds.

    Implements the same duck-typed interface as Slack's chat_stream() result:
      async append(*, markdown_text: str) -> None
      async stop(blocks: list[dict] | None = None) -> None
    """

    def __init__(self, service, space_name: str, message_name: str, thread_key: str):
        self._service = service
        self._space_name = space_name
        self._message_name = message_name
        self._thread_key = thread_key
        self._buffer = ""
        self._accumulated = ""
        self._last_update = time.monotonic()

    async def append(self, *, text: str = "", markdown_text: str = ""):
        content = markdown_text or text
        self._buffer += content
        now = time.monotonic()
        if now - self._last_update > FLUSH_INTERVAL:
            await self._flush()

    async def stop(self, blocks=None, cards=None):
        await self._flush(final=True, cards=cards or blocks)

    async def _flush(self, final=False, cards=None):
        if not self._buffer and not final:
            return
        self._accumulated += self._buffer
        self._buffer = ""
        self._last_update = time.monotonic()
        if not self._accumulated and not cards:
            return

        body: dict = {}
        if self._accumulated:
            body["text"] = self._accumulated
        if cards:
            body["cardsV2"] = cards

        update_mask = ",".join(body.keys())
        try:
            await asyncio.to_thread(
                self._service.spaces()
                .messages()
                .update(
                    name=self._message_name,
                    updateMask=update_mask,
                    body=body,
                )
                .execute
            )
        except Exception:
            logger.error(
                "Failed to update Google Chat message %s",
                self._message_name,
                exc_info=True,
            )
