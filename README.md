# Sandstorm

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![OpenRouter](https://img.shields.io/badge/OpenRouter-300%2B_models-6366f1.svg)](https://openrouter.ai)
[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2Ftomascupr%2Fsandstorm&env=ANTHROPIC_API_KEY,E2B_API_KEY)

**Hundreds of AI agents running in parallel. Hours-long tasks. Tool use, file access, structured output — each in its own secure sandbox. Sounds hard. It's not.**

```bash
curl -N -X POST https://your-sandstorm-host/query \
  -d '{"prompt": "Scrape the top 50 YC companies, enrich with funding data, save as PNG + CSV and contact founders on LinkedIn"}'
```

That's the entire integration. One POST request. The agent installs dependencies, fetches live data, builds a database, generates files, and streams every step back to you in real-time. When it's done, the sandbox is destroyed. Nothing persists. Nothing escapes.

Sandstorm wraps the [Claude Agent SDK](https://docs.anthropic.com/en/docs/agents-and-tools/claude-agent-sdk) in isolated [E2B](https://e2b.dev) cloud sandboxes so you can give AI agents full system access without worrying about what they do with it. Run Anthropic models, or swap in any of 300+ models via [OpenRouter](https://openrouter.ai). No Docker setup, no permission systems, no infrastructure to manage. Just a prompt in, results out.

- **Scales to zero effort** -- no infra to manage, no containers to orchestrate, no cleanup to handle
- **Full agent power** -- Bash, Read, Write, Edit, Glob, Grep, WebSearch, WebFetch -- all enabled by default
- **Safe by design** -- every request gets a fresh VM that's destroyed after, with zero state leakage
- **Real-time streaming** -- watch the agent work step-by-step via SSE, not just the final answer
- **Configure once, query forever** -- drop a `sandstorm.json` for structured output, subagents, MCP servers, and system prompts
- **File uploads** -- send code, data, or configs for the agent to work with
- **Any model via OpenRouter** -- run agents on Claude, GPT-4o, Qwen, Llama, DeepSeek, Gemini, or any of 300+ models through [OpenRouter](https://openrouter.ai)
- **BYOK** -- bring your own Anthropic, OpenRouter, or cloud provider keys, or set them once in `.env`

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2Ftomascupr%2Fsandstorm&env=ANTHROPIC_API_KEY,E2B_API_KEY)

## Table of Contents

- [Quickstart](#quickstart)
- [How It Works](#how-it-works)
- [Features](#features)
- [OpenRouter](#openrouter)
- [Configuration](#configuration)
- [API Reference](#api-reference)
- [Client Examples](#client-examples)
- [Deployment](#deployment)
- [Security](#security)

## Quickstart

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- [E2B](https://e2b.dev) API key
- [Anthropic](https://console.anthropic.com) API key or [OpenRouter](https://openrouter.ai) API key

### Setup

```bash
git clone https://github.com/tomascupr/sandstorm.git
cd sandstorm
uv sync

# Set your API keys
cp .env.example .env   # then edit with your keys

# Start the server
uv run python -m uvicorn sandstorm.main:app --reload

# Run your first agent
curl -N -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Find the top 10 trending Python repos on GitHub and summarize each in one sentence"}'
```

### E2B Sandbox Template

Sandstorm ships with a public pre-built template (`work-43ca/sandstorm`) that's used automatically — no build step needed. The template includes Node.js 24, `@anthropic-ai/claude-agent-sdk`, Python 3, git, ripgrep, and curl.

To customize the template (e.g. add system packages or pre-install other dependencies), edit `build_template.py` and rebuild:

```bash
uv run python build_template.py
```

## How It Works

```
Client --POST /query--> FastAPI --> E2B Sandbox (isolated VM)
  <---- SSE stream <---- stdout <-- runner.mjs --> query() from Agent SDK
                                     |-- Bash, Read, Write, Edit
                                     |-- Glob, Grep, WebSearch, WebFetch
                                     '-- subagents, MCP servers, structured output
```

1. Your app sends a prompt to `POST /query`
2. Sandstorm creates a fresh E2B sandbox with the Claude Agent SDK pre-installed
3. The agent runs your prompt with full tool access inside the sandbox
4. Every agent message (thoughts, tool calls, results) streams back as SSE events
5. The sandbox is destroyed when done -- nothing persists

## Features

### Structured Output

Configure in `sandstorm.json` to get validated JSON instead of free-form text:

```json
{
  "output_format": {
    "type": "json_schema",
    "schema": {
      "type": "object",
      "properties": {
        "companies": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "name": { "type": "string" },
              "funding_total": { "type": "number" },
              "sector": { "type": "string" },
              "url": { "type": "string" }
            },
            "required": ["name", "funding_total", "sector"]
          }
        },
        "files_created": {
          "type": "array",
          "items": { "type": "string" }
        }
      },
      "required": ["companies", "files_created"]
    }
  }
}
```

The agent works normally (scrapes data, installs packages, writes files), then returns validated JSON in `result.structured_output`.

### Subagents

Define specialized agents in `sandstorm.json` that the main agent can delegate to:

```json
{
  "agents": {
    "scraper": {
      "description": "Crawls websites and saves structured data to disk.",
      "prompt": "Scrape the target, extract data, and save as JSON to /home/user/output/.",
      "tools": ["Bash", "WebFetch", "Write", "Read"],
      "model": "sonnet"
    },
    "report-writer": {
      "description": "Reads collected data and produces formatted reports.",
      "prompt": "Read all data files, synthesize findings, and generate a PDF report with charts.",
      "tools": ["Bash", "Read", "Write", "Glob"]
    }
  }
}
```

The main agent spawns subagents via the `Task` tool when it decides they're needed.

### File Uploads

Send files in the request for the agent to work with:

```bash
curl -N -X POST https://your-sandstorm-host/query \
  -d '{
    "prompt": "Parse these server logs, find error spikes, and write an incident report",
    "files": {
      "logs/app.log": "2024-01-15T10:23:01Z ERROR [auth] connection pool exhausted\n...",
      "logs/deploys.json": "[{\"sha\": \"a1b2c3\", \"ts\": \"2024-01-15T10:20:00Z\"}]"
    }
  }'
```

Files are written to `/home/user/{path}` in the sandbox before the agent starts.

### MCP Servers

Attach external tools via [MCP](https://modelcontextprotocol.io) in `sandstorm.json`:

```json
{
  "mcp_servers": {
    "sqlite": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-sqlite", "/home/user/data.db"]
    },
    "remote-api": {
      "type": "sse",
      "url": "https://api.example.com/mcp/sse",
      "headers": { "Authorization": "Bearer your-token" }
    }
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `type` | `string` | `"stdio"`, `"http"`, or `"sse"` |
| `command` | `string` | Command for stdio servers |
| `args` | `string[]` | Command arguments |
| `url` | `string` | URL for HTTP/SSE servers |
| `headers` | `object` | Auth headers for remote servers |
| `env` | `object` | Environment variables |

## OpenRouter

Sandstorm works with any model available on [OpenRouter](https://openrouter.ai) -- not just Claude. Run agents powered by GPT-4o, Qwen, Llama, DeepSeek, Gemini, Mistral, or any of 300+ models, all through the same API.

### Setup

Add three env vars to `.env`:

```bash
ANTHROPIC_BASE_URL=https://openrouter.ai/api
OPENROUTER_API_KEY=sk-or-...
ANTHROPIC_DEFAULT_SONNET_MODEL=anthropic/claude-sonnet-4  # or any OpenRouter model ID
```

That's it. The agent now routes through OpenRouter. Your existing `ANTHROPIC_API_KEY` can stay in `.env` -- Sandstorm automatically clears it in the sandbox when OpenRouter is active.

### Using Open-Source Models

Remap the SDK's model aliases to any OpenRouter model:

```bash
# Route "sonnet" to Qwen
ANTHROPIC_DEFAULT_SONNET_MODEL=qwen/qwen3-max-thinking

# Route "opus" to DeepSeek
ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek/deepseek-r1

# Route "haiku" to a fast, cheap model
ANTHROPIC_DEFAULT_HAIKU_MODEL=qwen/qwen3-30b-a3b
```

Then use the alias in your request or `sandstorm.json`:

```bash
curl -N -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Analyze this CSV and build a chart", "model": "sonnet"}'
```

The agent runs on Qwen, DeepSeek, or whatever you mapped -- with full tool use, file access, and streaming.

### Per-Request Keys

Pass `openrouter_api_key` in the request body for multi-tenant setups:

```bash
curl -N -X POST http://localhost:8000/query \
  -d '{"prompt": "...", "openrouter_api_key": "sk-or-...", "model": "sonnet"}'
```

### How It Works

The Claude Agent SDK supports custom API endpoints via `ANTHROPIC_BASE_URL`. OpenRouter exposes an Anthropic-compatible API, so the SDK sends requests to OpenRouter instead of Anthropic directly. OpenRouter then routes to whatever model you've configured. The `ANTHROPIC_DEFAULT_*_MODEL` env vars tell the SDK which model ID to send when you use aliases like `sonnet` or `opus`.

### Compatibility

Most models on OpenRouter support the core agent capabilities (tool use, streaming, multi-turn). Models with strong tool-use support (Claude, GPT-4o, Qwen, DeepSeek) work best. Smaller or older models may struggle with complex tool chains.

Browse available models at [openrouter.ai/models](https://openrouter.ai/models).

## Configuration

Sandstorm uses a two-layer config system:

| Layer | What it controls | How to set |
|-------|-----------------|------------|
| **`sandstorm.json`** | Agent behavior -- system prompt, structured output, subagents, MCP servers | Config file in project root |
| **API request** | Per-call -- prompt, model, files, timeout | JSON body on `POST /query` |

### `sandstorm.json`

Drop a `sandstorm.json` in your project root to configure the agent's behavior:

```json
{
  "system_prompt": "You are a due diligence analyst. Write reports to /home/user/output/.",
  "model": "sonnet",
  "max_turns": 20
}
```

See [Structured Output](#structured-output), [Subagents](#subagents), and [MCP Servers](#mcp-servers) for advanced configuration.

| Field | Type | Description |
|-------|------|-------------|
| `system_prompt` | `string` | Custom instructions for the agent |
| `model` | `string` | Default model (`"sonnet"`, `"opus"`, `"haiku"`, or full ID) |
| `max_turns` | `integer` | Maximum conversation turns |
| `output_format` | `object` | JSON schema for [structured output](#structured-output) |
| `agents` | `object` | [Subagent](#subagents) definitions |
| `mcp_servers` | `object` | [MCP server](#mcp-servers) configurations |

### API Keys

Keys can live in `.env` (set once) or be passed per-request (multi-tenant). Request body overrides `.env`.

```bash
# .env -- set once, forget about it
ANTHROPIC_API_KEY=sk-ant-...
E2B_API_KEY=e2b_...

# Then just send prompts:
curl -N -X POST https://your-sandstorm-host/query \
  -d '{"prompt": "Crawl docs.stripe.com/api and generate an OpenAPI spec as YAML"}'

# Or override per-request:
curl -N -X POST https://your-sandstorm-host/query \
  -d '{"prompt": "...", "anthropic_api_key": "sk-ant-other", "e2b_api_key": "e2b_other"}'
```

### Providers

Sandstorm supports Anthropic (default), Google Vertex AI, Amazon Bedrock, Microsoft Azure, [OpenRouter](#openrouter), and custom API proxies. Add the env vars to `.env` and restart -- the SDK detects them automatically.

| Provider | Key env vars |
|----------|-------------|
| **Anthropic** (default) | `ANTHROPIC_API_KEY` |
| **[OpenRouter](#openrouter)** | `ANTHROPIC_BASE_URL`, `OPENROUTER_API_KEY` (see [OpenRouter](#openrouter)) |
| **Vertex AI** | `CLAUDE_CODE_USE_VERTEX=1`, `CLOUD_ML_REGION`, `ANTHROPIC_VERTEX_PROJECT_ID` |
| **Bedrock** | `CLAUDE_CODE_USE_BEDROCK=1`, `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` |
| **Azure** | `CLAUDE_CODE_USE_FOUNDRY=1`, `AZURE_FOUNDRY_RESOURCE`, `AZURE_API_KEY` |
| **Custom proxy** | `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN` (optional) |

## API Reference

### `POST /query`

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `prompt` | `string` | Yes | -- | The task for the agent (min 1 char) |
| `anthropic_api_key` | `string` | No | `$ANTHROPIC_API_KEY` | Anthropic key (falls back to env) |
| `openrouter_api_key` | `string` | No | `$OPENROUTER_API_KEY` | OpenRouter key (falls back to env) |
| `e2b_api_key` | `string` | No | `$E2B_API_KEY` | E2B key (falls back to env) |
| `model` | `string` | No | from config | Overrides `sandstorm.json` model |
| `max_turns` | `integer` | No | from config | Overrides `sandstorm.json` max_turns |
| `timeout` | `integer` | No | `300` | Sandbox lifetime in seconds |
| `files` | `object` | No | `null` | Files to upload (`{path: content}`) |

**Response:** `text/event-stream`

### `GET /health`

Returns `{"status": "ok"}`

### SSE Event Types

| Type | Description |
|------|-------------|
| `system` | Session init -- tools, model, session ID |
| `assistant` | Agent text + tool calls |
| `user` | Tool execution results |
| `result` | Final result with `total_cost_usd`, `num_turns`, and optional `structured_output` |
| `error` | Error details (only on failure) |

## Client Examples

### Python

```python
import httpx
from httpx_sse import connect_sse

with httpx.Client() as client:
    with connect_sse(
        client, "POST",
        "https://your-sandstorm-host/query",
        json={
            "prompt": "Scrape the top 50 HN stories, cluster by topic, save to output/hn.csv"
        },
    ) as events:
        for sse in events.iter_sse():
            print(sse.data)
```

### TypeScript

```typescript
const res = await fetch("https://your-sandstorm-host/query", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    prompt: "Fetch recent arxiv papers on LLM agents, extract findings, write a lit review",
  }),
});

const reader = res.body!.getReader();
const decoder = new TextDecoder();
while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  console.log(decoder.decode(value));
}
```

## Deployment

Sandstorm is a stateless FastAPI app. Each request creates an independent E2B sandbox, runs the agent, and tears it down. No shared state, no sticky sessions, no coordination between requests. This means deploying for concurrent agent runs is trivial -- just add workers.

### Production Server

Use [Gunicorn](https://gunicorn.org/) with uvicorn workers. Each worker handles multiple concurrent requests via async I/O:

```bash
pip install gunicorn
gunicorn sandstorm.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 4 \
  --bind 0.0.0.0:8000 \
  --timeout 600
```

Set `--workers` based on your machine (2× CPU cores is a reasonable starting point). Set `--timeout` higher than your longest expected agent run.

### Running Many Agents Concurrently

Fire as many requests as you want. Each one gets its own sandbox:

```python
import asyncio
import httpx
from httpx_sse import aconnect_sse


async def run_agent(client: httpx.AsyncClient, prompt: str):
    async with aconnect_sse(
        client, "POST", "http://localhost:8000/query",
        json={"prompt": prompt},
    ) as events:
        async for sse in events.aiter_sse():
            print(sse.data)


async def main():
    prompts = [
        "Scrape the top 50 YC companies and save as CSV",
        "Analyze Python dependency security for requests==2.31.0",
        "Fetch today's arxiv papers on LLM agents and write a summary",
        "Build a SQLite DB of US national parks from NPS.gov",
    ]
    async with httpx.AsyncClient(timeout=600) as client:
        await asyncio.gather(*[run_agent(client, p) for p in prompts])

asyncio.run(main())
```

All four agents run simultaneously in isolated sandboxes. They can't see each other. When one finishes, its VM is destroyed -- the others keep running.

### Scaling

The Sandstorm server does almost no work itself -- it just proxies between your client and E2B. The real compute happens in E2B's cloud VMs. This means:

- **Horizontal scaling** -- run multiple Sandstorm instances behind a load balancer. No shared state to worry about.
- **Bottleneck is E2B** -- your concurrent sandbox limit depends on your [E2B plan](https://e2b.dev/pricing). The free tier allows a handful; paid plans scale higher.
- **CPU/memory on the server is minimal** -- each request holds an open SSE connection and streams stdout. A single 2-core machine can comfortably handle dozens of concurrent agents.

### Docker

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .
EXPOSE 8000
CMD ["gunicorn", "sandstorm.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "4", "--bind", "0.0.0.0:8000", "--timeout", "600"]
```

```bash
docker build -t sandstorm .
docker run -p 8000:8000 --env-file .env sandstorm
```

Deploy this container to any platform -- Railway, Fly.io, Cloud Run, ECS, Kubernetes. Since there's no state to persist, scaling up or down is just changing the replica count.

### Vercel

One-click deploy:

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2Ftomascupr%2Fsandstorm&env=ANTHROPIC_API_KEY,E2B_API_KEY)

The repo includes `vercel.json` and `api/index.py` pre-configured. Set `ANTHROPIC_API_KEY` and `E2B_API_KEY` as environment variables in your Vercel project settings.

> **Note:** Vercel serverless functions have a maximum duration of 300s on Pro plans (10s on Hobby). For long-running agent tasks, use the Docker deployment or a dedicated server instead.

## Security

- **Isolated execution** -- every request gets a fresh VM sandbox, destroyed after
- **No server secrets** -- keys via `.env` or per-request, never stored server-side
- **No shell injection** -- prompts and config written as files, never interpolated into commands
- **Path traversal prevention** -- file upload paths are normalized and validated
- **Structured errors** -- failures stream as SSE error events, not silent drops
- **No persistence** -- nothing survives between requests

> **Note:** The Anthropic API key is passed into the sandbox as an environment variable (the SDK requires it). The agent runs with `bypassPermissions` mode, so it has full access to the sandbox environment. Use per-request keys with spending limits for untrusted callers.

## License

[MIT](LICENSE)
