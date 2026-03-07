# API reference

## Authentication

Sandstorm supports optional Bearer token authentication on `/query`.

```bash
export SANDSTORM_API_KEY="your-secret-token-at-least-32-characters-long"

curl -N -X POST https://your-sandstorm-host/query \
  -H "Authorization: Bearer $SANDSTORM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello world"}'
```

Key rotation is supported through `SANDSTORM_API_KEY_PREVIOUS`. The `/health` endpoint stays public.

## `POST /query`

Runs an agent request and returns a `text/event-stream` response.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `prompt` | `string` | Yes | - | The task for the agent |
| `anthropic_api_key` | `string` | No | `$ANTHROPIC_API_KEY` | Anthropic key override |
| `openrouter_api_key` | `string` | No | `$OPENROUTER_API_KEY` | OpenRouter key override |
| `e2b_api_key` | `string` | No | `$E2B_API_KEY` | E2B key override |
| `model` | `string` | No | from config | Overrides `sandstorm.json` |
| `max_turns` | `integer` | No | from config | Overrides `sandstorm.json` |
| `timeout` | `integer` | No | `300` | Sandbox lifetime in seconds |
| `files` | `object` | No | `null` | Files to upload as `{path: content}` |
| `output_format` | `object` | No | from config | Structured output override |
| `allowed_mcp_servers` | `string[]` | No | `null` | MCP whitelist by config name |
| `allowed_skills` | `string[]` | No | `null` | Skills whitelist by config name |
| `allowed_tools` | `string[]` | No | from config | Tool override |
| `allowed_agents` | `string[]` | No | `null` | Agent whitelist by config name |
| `extra_agents` | `object` | No | `null` | Inline agent definitions |
| `extra_skills` | `object` | No | `null` | Inline skill definitions |

Example:

```bash
curl -N -X POST https://your-sandstorm-host/query \
  -H "Authorization: Bearer $SANDSTORM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Crawl docs.stripe.com/api and generate a draft OpenAPI spec",
    "model": "sonnet",
    "timeout": 300
  }'
```

## SSE events

`POST /query` streams newline-delimited JSON events.

| Type | Description |
|------|-------------|
| `system` | Session initialization with tool and model metadata |
| `assistant` | Agent text blocks and tool calls |
| `user` | Tool execution results |
| `result` | Final result with turns, cost, and optional `structured_output` |
| `warning` | Best-effort warning emitted during streaming |
| `error` | Failure payload |

## `GET /runs`

Returns recent agent runs as JSON, newest first.

```json
[
  {
    "id": "a1b2c3d4",
    "prompt": "Create hello.py and run it",
    "model": "claude-sonnet-4-5-20250929",
    "status": "completed",
    "cost_usd": 0.069,
    "num_turns": 6,
    "duration_secs": 28.5,
    "started_at": "2025-02-18T22:10:30Z",
    "error": null,
    "files_count": 0
  }
]
```

## `GET /health`

Returns the service version and status:

```json
{
  "status": "ok",
  "version": "0.8.0"
}
```

Add `?deep=true` to verify configured API keys and E2B reachability.

## `POST /webhooks/e2b`

Receives E2B sandbox lifecycle events such as `created`, `updated`, and `killed`.

- Verifies HMAC-SHA256 signatures when `SANDSTORM_WEBHOOK_SECRET` is set
- Used automatically when `webhook_url` is configured in `sandstorm.json`
- Can also be exercised with `ds webhook test`
