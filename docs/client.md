# Python client

Use the async Python client when you want to call a Sandstorm server from your own app.

## Install

```bash
pip install "duvo-sandstorm[client]"
```

The `client` extra installs `httpx` and `httpx-sse`.

## Quick start

```python
import asyncio

from sandstorm import SandstormClient


async def main():
    async with SandstormClient(
        "http://localhost:8000",
        api_key="your-sandstorm-api-key",
    ) as client:
        health = await client.health()
        print(health)

        async for event in client.query(
            "Compare Notion, Coda, and Slite for async product teams",
            model="sonnet",
        ):
            if event.text:
                print(event.text, end="")


asyncio.run(main())
```

`api_key` is optional. Pass it when the server has `SANDSTORM_API_KEY` enabled.

## What it provides

- `SandstormClient.health()` for `GET /health`
- `SandstormClient.query()` for streaming `POST /query`
- `SandstormEvent.type` for the raw event type
- `SandstormEvent.data` for the full parsed event payload
- `SandstormEvent.text` for concatenated assistant text blocks

## Query arguments

`query()` accepts the common request fields directly:

- `prompt`
- `model`
- `max_turns`
- `timeout`
- `files`

Any additional keyword arguments are forwarded to `POST /query`, so request-level options such as
`allowed_tools`, `allowed_agents`, `allowed_skills`, `allowed_mcp_servers`, `extra_agents`, and
`extra_skills` work the same way as the HTTP API.

## Notes

- Use `async with` so the underlying HTTP client is created and closed correctly.
- `health()` stays public even when API auth is enabled.
- `query()` raises a runtime error if the `client` extra is not installed.

For the full request schema and SSE event types, see the [API reference](api.md).
