# Sandstorm

Run AI agents in secure cloud sandboxes. One command. Zero infrastructure.

[![Claude Agent SDK](https://img.shields.io/badge/Claude_Agent_SDK-black?logo=anthropic)](https://platform.claude.com/docs/en/agent-sdk/overview)
[![E2B](https://img.shields.io/badge/E2B-sandboxed-ff8800.svg)](https://e2b.dev)
[![OpenRouter](https://img.shields.io/badge/OpenRouter-300%2B_models-6366f1.svg)](https://openrouter.ai)
[![PyPI](https://img.shields.io/pypi/v/duvo-sandstorm.svg)](https://pypi.org/project/duvo-sandstorm/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Hundreds of AI agents running in parallel. Hours-long tasks. Tool use, file access, structured output — each in its own secure sandbox. Sounds hard. It's not.**

```bash
ds "Fetch all our webpages from git, analyze each for SEO and GEO, optimize them, and push the changes back"
```

That's it. Sandstorm wraps the [Claude Agent SDK](https://platform.claude.com/docs/en/agent-sdk/overview) in isolated [E2B](https://e2b.dev) cloud sandboxes — the agent installs packages, fetches live data, generates files, and streams every step back via SSE. When it's done, the sandbox is destroyed. Nothing persists. Nothing escapes.

### Why Sandstorm?

Most companies want to use AI agents but hit the same wall: infrastructure, security concerns, and complexity. Sandstorm removes all three. It's a simplified, open-source version of the agent runtime we built at [duvo.ai](https://duvo.ai) — battle-tested in production.

- **Any model via OpenRouter** -- swap in DeepSeek R1, Qwen 3, Kimi K2, or any of 300+ models through [OpenRouter](https://openrouter.ai)
- **Full agent power** -- Bash, Read, Write, Edit, Glob, Grep, WebSearch, WebFetch -- all enabled by default
- **Safe by design** -- every request gets a fresh VM that's destroyed after, with zero state leakage
- **Real-time streaming** -- watch the agent work step-by-step via SSE, not just the final answer
- **Configure once, query forever** -- drop a `sandstorm.json` for structured output, subagents, MCP servers, and system prompts
- **File uploads** -- send code, data, or configs for the agent to work with

### Get Started

```bash
pip install duvo-sandstorm
export ANTHROPIC_API_KEY=sk-ant-...
export E2B_API_KEY=e2b_...
ds "Find the top 10 trending Python repos on GitHub and summarize each in one sentence"
```

If Sandstorm is useful, consider giving it a [star](https://github.com/tomascupr/sandstorm) — it helps others find it.

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2Ftomascupr%2Fsandstorm&env=ANTHROPIC_API_KEY,E2B_API_KEY)

## Quickstart

### Prerequisites

- Python 3.11+
- [E2B](https://e2b.dev) API key
- [Anthropic](https://console.anthropic.com) API key or [OpenRouter](https://openrouter.ai) API key
- [uv](https://docs.astral.sh/uv/) (only for source installs)

### Install

```bash
# From PyPI
pip install duvo-sandstorm

# Or from source
git clone https://github.com/tomascupr/sandstorm.git
cd sandstorm
uv sync
```

### E2B Sandbox Template

Sandstorm ships with a public pre-built template (`work-43ca/sandstorm`) that's used automatically — no build step needed. The template includes Node.js 24, `@anthropic-ai/claude-agent-sdk`, Python 3, git, ripgrep, and curl.

To customize the template (e.g. add system packages or pre-install other dependencies), edit `build_template.py` and rebuild:

```bash
uv run python build_template.py
```

## CLI

After installing, the `duvo-sandstorm` (or `ds`) command is available:

### Run an agent

The `query` command is the default — just pass a prompt directly:

```bash
ds "Create hello.py and run it"
ds "Analyze this repo" --model opus
ds "Build a chart" --max-turns 30 --timeout 600
ds "Fetch data" --json-output | jq '.type'
```

The explicit `query` subcommand also works: `ds query "Create hello.py"`.

### Upload files

Use `-f` / `--file` to send local files into the sandbox (repeatable):

```bash
ds "Analyze this data and find outliers" -f data.csv
ds "Compare these configs" -f prod.json -f staging.json
ds "Review this code for bugs" -f src/main.py -f src/utils.py
```

Files are uploaded to `/home/user/{filename}` before the agent starts. Only text files are supported; binary files must be sent via the [API](#file-uploads) instead.

### Start the server

```bash
ds serve                    # default: 0.0.0.0:8000
ds serve --port 3000        # custom port
ds serve --reload           # auto-reload for development
```

### API keys

Keys are resolved in order: CLI flags > environment variables > `.env` file in current directory.

```bash
# Environment variables (most common)
export ANTHROPIC_API_KEY=sk-ant-...
export E2B_API_KEY=e2b_...

# Or CLI flags
ds "hello" --anthropic-api-key sk-ant-... --e2b-api-key e2b_...
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
        "summary": { "type": "string" },
        "items": { "type": "array", "items": { "type": "object" } }
      },
      "required": ["summary", "items"]
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

Files are written to `/home/user/{path}` in the sandbox before the agent starts. From the CLI, use `-f` / `--file` instead (see [Upload files](#upload-files)).

### Skills

Skills give the agent reusable domain knowledge via [Claude Code Skills](https://docs.anthropic.com/en/docs/claude-code/skills). Each skill is a folder with a `SKILL.md` file — Sandstorm uploads them into the sandbox before the agent starts, where they become available as `/slash-commands`.

Create a skills directory with one subfolder per skill, each containing a `SKILL.md`:

```
.claude/skills/
  code-review/
    SKILL.md
  data-analyst/
    SKILL.md
```

Then point `skills_dir` in `sandstorm.json` to it:

```json
{
  "skills_dir": ".claude/skills"
}
```

Each skill becomes a slash command the agent can use — a folder named `data-analyst` registers as `/data-analyst`. Names must contain only letters, numbers, hyphens, and underscores.

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

## Examples

Ready-to-use configs for common use cases — `cd` into any example and run:

| Example | What it does | Key features |
|---------|-------------|--------------|
| [Code Reviewer](examples/code-reviewer/) | Structured code review with severity ratings | `output_format`, `allowed_tools` |
| [Competitive Analysis](examples/competitive-analysis/) | Research and compare competitors | `output_format`, WebFetch, WebSearch |
| [Content Brief](examples/content-brief/) | Generate content briefs with SEO research | `output_format`, WebSearch |
| [Security Auditor](examples/security-auditor/) | Multi-agent security audit with OWASP skill | `agents`, `skills_dir`, `output_format` |

See [examples/](examples/) for the full feature matrix and usage guide.

## OpenRouter

Use any of 300+ models (GPT-4o, Qwen, DeepSeek, Gemini, Llama) via [OpenRouter](https://openrouter.ai). Three env vars to set up:

```bash
ANTHROPIC_BASE_URL=https://openrouter.ai/api
OPENROUTER_API_KEY=sk-or-...
ANTHROPIC_DEFAULT_SONNET_MODEL=anthropic/claude-sonnet-4  # or any model ID
```

For model remapping, per-request keys, and compatibility details, see the [full OpenRouter guide](docs/openrouter.md).

## Configuration

Sandstorm uses a two-layer config system:

| Layer | What it controls | How to set |
|-------|-----------------|------------|
| **`sandstorm.json`** | Agent behavior -- system prompt, structured output, subagents, MCP servers | Config file in project root |
| **API request** | Per-call -- prompt, model, files, timeout | JSON body on `POST /query` |

### `sandstorm.json`

Drop a `sandstorm.json` in your project root. See [Structured Output](#structured-output), [Subagents](#subagents), and [MCP Servers](#mcp-servers) for feature-specific examples.

| Field | Type | Description |
|-------|------|-------------|
| `system_prompt` | `string` | Custom instructions for the agent |
| `model` | `string` | Default model (`"sonnet"`, `"opus"`, `"haiku"`, or full ID) |
| `max_turns` | `integer` | Maximum conversation turns |
| `output_format` | `object` | JSON schema for [structured output](#structured-output) |
| `agents` | `object` | [Subagent](#subagents) definitions |
| `mcp_servers` | `object` | [MCP server](#mcp-servers) configurations |
| `skills_dir` | `string` | Path to directory containing [skills](#skills) subdirectories |
| `allowed_tools` | `list` | Restrict agent to specific tools (e.g. `["Bash", "Read"]`). `"Skill"` is auto-added when skills are present |

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

Sandstorm is stateless -- each request creates an independent sandbox. No shared state, no sticky sessions. For production deployment with Gunicorn, concurrent agent execution, and scaling guidance, see the [deployment guide](docs/deployment.md).

### Docker

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .  # or: pip install duvo-sandstorm
EXPOSE 8000
CMD ["ds", "serve", "--host", "0.0.0.0", "--port", "8000"]
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
