"""Google Chat bot integration for Sandstorm."""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)

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
