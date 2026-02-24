"""Async Python client for the Sandstorm API."""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import TracebackType


@dataclass
class SandstormEvent:
    """A single event from the Sandstorm SSE stream."""

    type: str
    data: dict

    @property
    def text(self) -> str | None:
        """Extract assistant text content, if any."""
        if self.type != "assistant":
            return None
        parts = []
        for block in self.data.get("message", {}).get("content", []):
            if block.get("type") == "text":
                parts.append(block["text"])
        return "".join(parts) if parts else None


class SandstormClient:
    """Async client for the Sandstorm API.

    Usage::

        async with SandstormClient("https://your-host") as client:
            async for event in client.query("Hello world"):
                print(event.type, event.data)
    """

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout: float = 300,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._client = None

    async def __aenter__(self) -> SandstormClient:
        import httpx

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(self.timeout, connect=10),
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._client:
            await self._client.aclose()

    async def health(self) -> dict:
        """Check server health."""
        if self._client is None:
            raise RuntimeError("Use 'async with' to create the client")
        resp = await self._client.get("/health")
        resp.raise_for_status()
        return resp.json()

    async def query(
        self,
        prompt: str,
        *,
        model: str | None = None,
        max_turns: int | None = None,
        timeout: int | None = None,
        files: dict[str, str] | None = None,
        **kwargs,
    ):
        """Send a query and yield SandstormEvent objects from the SSE stream.

        Args:
            prompt: The task for the agent.
            model: Optional model override.
            max_turns: Optional max turns override.
            timeout: Optional sandbox timeout in seconds.
            files: Optional files to upload ({path: content}).
            **kwargs: Additional fields passed to POST /query.

        Yields:
            SandstormEvent for each SSE event.
        """
        from httpx_sse import aconnect_sse

        if self._client is None:
            raise RuntimeError("Use 'async with' to create the client")

        body: dict = {"prompt": prompt, **kwargs}
        if model is not None:
            body["model"] = model
        if max_turns is not None:
            body["max_turns"] = max_turns
        if timeout is not None:
            body["timeout"] = timeout
        if files is not None:
            body["files"] = files

        async with aconnect_sse(self._client, "POST", "/query", json=body) as event_source:
            async for sse in event_source.aiter_sse():
                try:
                    data = json.loads(sse.data)
                except (json.JSONDecodeError, TypeError):
                    continue
                yield SandstormEvent(type=data.get("type", "unknown"), data=data)
