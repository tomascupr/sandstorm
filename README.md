# Sandstorm

**Deploying AI agents that can write files, run commands, and use tools to the cloud sounds hard. It's not.**

```bash
curl -N -X POST https://your-sandstorm-host/query \
  -d '{"prompt": "Scrape the top 50 YC companies from this batch, enrich each with Crunchbase funding data, save to a SQLite database, then generate a market map as a PNG and a CSV export"}'
```

That's the entire integration. One POST request. The agent installs dependencies, fetches live data, builds a database, generates files, and streams every step back to you in real-time. When it's done, the sandbox is destroyed. Nothing persists. Nothing escapes.

Sandstorm wraps the [Claude Agent SDK](https://docs.anthropic.com/en/docs/agents-and-tools/claude-agent-sdk) in isolated [E2B](https://e2b.dev) cloud sandboxes so you can give AI agents full system access without worrying about what they do with it. No Docker setup, no permission systems, no infrastructure to manage. Just a prompt in, results out.

## Why Sandstorm?

Building agents that can actually *do things* — research the web, analyze data, process files, run scripts — typically means dealing with sandboxing, process isolation, permission management, and cleanup. Sandstorm reduces all of that to a single API call.

- **Scales to zero effort** — no infra to manage, no containers to orchestrate, no cleanup to handle
- **Full agent power** — Bash, Read, Write, Edit, Glob, Grep, WebSearch, WebFetch — all enabled by default
- **Safe by design** — every request gets a fresh VM that's destroyed after, with zero state leakage
- **Real-time streaming** — watch the agent work step-by-step via SSE, not just the final answer
- **Configure once, query forever** — drop a `sandstorm.json` in your project for structured output, subagents, MCP servers, and system prompts
- **File uploads** — send code, data, or configs for the agent to work with
- **BYOK** — bring your own Anthropic + E2B keys, or set them once in `.env`

## Quickstart

```bash
git clone https://github.com/tomascupr/sandstorm.git
cd sandstorm
uv sync

# Set your API keys
cp .env.example .env   # then edit with your keys

# Start the server
uv run python -m uvicorn claude_sandbox.main:app --reload

# Run your first agent
curl -N -X POST https://your-sandstorm-host/query \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Download the latest SEC 10-K filing for Tesla, extract all financial tables into CSVs, calculate YoY growth rates, and write a 2-page analysis report as a PDF"}'
```

**Optional:** Build a custom E2B template for instant cold starts (otherwise the SDK is installed at runtime, ~15s overhead):
```bash
uv run python build_template.py
```

## How It Works

```
Client ──POST /query──▶ FastAPI ──▶ E2B Sandbox (isolated VM)
  ◀──── SSE stream ◀──── stdout ◀── runner.mjs ──▶ query() from Agent SDK
                                     ├─ Bash, Read, Write, Edit
                                     ├─ Glob, Grep, WebSearch, WebFetch
                                     └─ subagents, MCP servers, structured output
```

1. Your app sends a prompt to `POST /query`
2. Sandstorm creates a fresh E2B sandbox with the Claude Agent SDK pre-installed
3. The agent runs your prompt with full tool access inside the sandbox
4. Every agent message (thoughts, tool calls, results) streams back as SSE events
5. The sandbox is destroyed when done — nothing persists

---

## Configuration

Sandstorm uses a two-layer config system:

| Layer | What it controls | How to set |
|-------|-----------------|------------|
| **`sandstorm.json`** | Agent behavior — system prompt, structured output, subagents, MCP servers | Config file in project root |
| **API request** | Per-call — prompt, model, files, timeout | JSON body on `POST /query` |

### `sandstorm.json`

Drop a `sandstorm.json` in your project root to configure the agent's behavior. This is loaded automatically on every request.

```json
{
  "system_prompt": "You are a due diligence analyst. Write reports to /home/user/output/. Cite all sources.",
  "model": "sonnet",
  "max_turns": 20,
  "output_format": {
    "type": "json_schema",
    "schema": {
      "type": "object",
      "properties": {
        "summary": { "type": "string" },
        "files_created": { "type": "array", "items": { "type": "string" } },
        "success": { "type": "boolean" }
      },
      "required": ["summary", "files_created", "success"]
    }
  },
  "agents": {
    "web-scraper": {
      "description": "Scrapes websites and saves structured data to files.",
      "prompt": "Scrape the given URLs, extract structured data, and save results as JSON files.",
      "tools": ["Bash", "WebFetch", "Write", "Read"]
    }
  },
  "mcp_servers": {
    "sqlite": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-sqlite", "/home/user/data.db"]
    }
  }
}
```

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
# .env — set once, forget about it
ANTHROPIC_API_KEY=sk-ant-...
E2B_API_KEY=e2b_...

# Then just send prompts:
curl -N -X POST https://your-sandstorm-host/query \
  -d '{"prompt": "Crawl docs.stripe.com/api, extract every endpoint, and generate a complete OpenAPI spec as YAML"}'

# Or override per-request:
curl -N -X POST https://your-sandstorm-host/query \
  -d '{"prompt": "...", "anthropic_api_key": "sk-ant-other", "e2b_api_key": "e2b_other"}'
```

### Providers

Sandstorm supports Anthropic (default), Google Vertex AI, Amazon Bedrock, and Microsoft Azure. Configure in `.env` — provider env vars are auto-forwarded into the sandbox.

**Google Vertex AI:**
```bash
CLAUDE_CODE_USE_VERTEX=1
CLOUD_ML_REGION=us-east5
ANTHROPIC_VERTEX_PROJECT_ID=your-gcp-project-id
```

**Amazon Bedrock:**
```bash
CLAUDE_CODE_USE_BEDROCK=1
AWS_REGION=us-west-2
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
```

**Microsoft Azure (Foundry):**
```bash
CLAUDE_CODE_USE_FOUNDRY=1
AZURE_FOUNDRY_RESOURCE=your-resource
AZURE_API_KEY=your-azure-key
```

Just add the vars to `.env` and restart. The Claude Agent SDK detects them automatically and routes requests to the right provider.

---

## API Reference

### `POST /query`

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `prompt` | `string` | Yes | — | The task for the agent (min 1 char) |
| `anthropic_api_key` | `string` | No | `$ANTHROPIC_API_KEY` | Anthropic key (falls back to env) |
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
| `system` | Session init — tools, model, session ID |
| `assistant` | Agent text + tool calls |
| `user` | Tool execution results |
| `result` | Final result with `total_cost_usd`, `num_turns`, and optional `structured_output` |
| `error` | Error details (only on failure) |

---

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
        "files_created": { "type": "array", "items": { "type": "string" } }
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
      "prompt": "Scrape the target, extract structured data, and write results as JSON to /home/user/output/.",
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
    "prompt": "Parse these server logs, correlate error spikes with deployment timestamps, identify root causes, and write an incident report to output/report.md with timeline charts saved as PNGs",
    "files": {
      "logs/app.log": "2024-01-15T10:23:01Z ERROR [auth] connection pool exhausted\n2024-01-15T10:23:02Z ERROR [auth] connection pool exhausted\n...",
      "logs/deploys.json": "[{\"sha\": \"a1b2c3\", \"timestamp\": \"2024-01-15T10:20:00Z\", \"service\": \"auth\"}]"
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

---

## Client Examples

### Python

```python
import httpx
from httpx_sse import connect_sse

with httpx.Client() as client:
    with connect_sse(
        client, "POST", "https://your-sandstorm-host/query",
        json={"prompt": "Scrape the top 50 HN stories, enrich each with company data from their websites, cluster by sector, and save a ranked spreadsheet to output/hn_analysis.csv"},
    ) as events:
        for sse in events.iter_sse():
            print(sse.data)
```

### TypeScript

```typescript
const res = await fetch("https://your-sandstorm-host/query", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ prompt: "Fetch the latest arxiv papers on LLM agents, download the PDFs, extract key findings from each, and compile a literature review as a markdown file with a summary table" }),
});

const reader = res.body!.getReader();
const decoder = new TextDecoder();
while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  console.log(decoder.decode(value));
}
```

---

## Custom E2B Template

Build a template with the Agent SDK pre-installed for instant sandbox creation:

```bash
uv run python build_template.py
```

Includes: Node.js 24, `@anthropic-ai/claude-agent-sdk`, Python 3, git, ripgrep, curl.

Without it, Sandstorm falls back to installing the SDK at runtime (~15s per request).

## Security

- **Isolated execution** — every request gets a fresh VM sandbox, destroyed after
- **No server secrets** — keys via `.env` or per-request, never stored server-side
- **No shell injection** — prompts and config written as files, never interpolated into commands
- **Path traversal prevention** — file upload paths are normalized and validated
- **Structured errors** — failures stream as SSE error events, not silent drops
- **No persistence** — nothing survives between requests

> **Note:** The Anthropic API key is passed into the sandbox as an environment variable (the SDK requires it). The agent runs with `bypassPermissions` mode, so it has full access to the sandbox environment. Use per-request keys with spending limits for untrusted callers.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- [E2B](https://e2b.dev) API key
- [Anthropic](https://console.anthropic.com) API key

## License

[MIT](LICENSE)
