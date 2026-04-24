# Sandstorm

**Claude Agent SDK, or any LLM, as a sandboxed agent in your Slack, on your infra.**

CLI, HTTP API, Python client, Slack bot, and repo-local TypeScript client source over
the same runtime. Fresh sandbox per thread on the configured runtime, E2B by default,
with streaming, file uploads, replay, and OpenTelemetry traces out of the box.

[![CI](https://github.com/tomascupr/sandstorm/actions/workflows/ci.yml/badge.svg)](https://github.com/tomascupr/sandstorm/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/duvo-sandstorm.svg)](https://pypi.org/project/duvo-sandstorm/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/template/sandstorm)

## Why this exists

Anthropic shipped **Claude Managed Agents** (April 2026): great sandbox,
Anthropic-infra only, Claude-only. Vercel shipped **Slack Agent Skill + Chat
SDK**: great Slack wizard, Vercel-only, TypeScript-only. Neither runs on your
infrastructure; neither gives you other LLMs; neither emits to your
observability backend.

Sandstorm is the intersection. Self-hosted, multi-provider, Slack-native,
observable. The shortest path from `pip install` to a production agent that
runs on your terms.

## Who it's for

- Teams who want Claude-style agents in Slack but can't send runtime traffic
  to Anthropic or Vercel.
- Engineers on GPT-5 / Gemini / DeepSeek / Qwen / Kimi / Grok who still want
  the Claude Agent SDK's tool + skill + sandbox story.
- Anyone running Langfuse / Phoenix / Langsmith who refuses to operate blind
  because their agent vendor keeps telemetry in a closed console.

## What a run looks like

```bash
$ ds init research-brief && cd research-brief
$ ds "Research Acme's competitors, crawl their sites and recent news, and write a one-page briefing PDF with sources."

[tool: WebFetch]  competitor product pages + recent coverage
[tool: WebSearch] launches, pricing, positioning, buyer signals
[tool: Write]     briefing.pdf
[tool: Write]     reports/sources.md

--- Result: success | turns: 14 | cost: $0.0731 ---

artifacts:
  - briefing.pdf
  - reports/sources.md
```

Same prompt from Slack:

```
you:       @Sandstorm research Acme's competitors and post the briefing here
bot:       (paused thread sandbox resumed)
           🔧 WebFetch
           🔧 WebSearch
           🔧 Write
           Acme's top three competitors are ...
           [briefing.pdf uploaded]
           Model: sonnet | Turns: 14 | Cost: $0.0731 | Duration: 47.2s
```

## Three things only OSS can do

1. **Self-host**: runs on your Railway/Fly/K8s/Docker. Data stays in your network.
   The default E2B runtime is available self-hosted; Anthropic's Managed Agents are
   Anthropic-infra only.
2. **Every LLM**: Anthropic direct, OpenRouter (GPT-5, Gemini, DeepSeek, Qwen, Kimi,
   Grok), Vertex AI, Bedrock, Azure Foundry, any OpenAI-compatible base URL.
3. **Your observability**: OTel export to [Langfuse](docs/observability.md),
   Phoenix/Arize, Langsmith, or any OTLP backend. No vendor console.

## Sandstorm vs the closed alternatives

| Feature                    | Sandstorm | Claude Managed Agents | Vercel Slack Agent Skill | claude-code-slack-bot |
| -------------------------- | :-------: | :-------------------: | :----------------------: | :-------------------: |
| Self-hosted                |     ✅     |           ❌           |             ❌            |        ✅ (local)      |
| Sandboxed per thread       |     ✅     |           ✅           |             ✅            |           ❌           |
| Slack in the box           |     ✅     |           ❌           |             ✅            |           ✅           |
| Multi-provider (not just Claude) | ✅   |           ❌           |             ✅            |           ❌           |
| OTel traces to any backend |     ✅     |           ❌           |             ❌            |           ❌           |
| OSS license                |   MIT     |        Proprietary    |        Apache templates  |          MIT          |
| Runtime client source in repo | ✅  |           ❌           |             ✅            |           ❌           |
| Session resume + replay    |     ✅     |           ✅           |             ❌            |           ❌           |

Full side-by-side in [docs/comparison.md](docs/comparison.md);
"when should I pick each?" in [docs/faq-vs-managed-agents.md](docs/faq-vs-managed-agents.md).

## 60-second quickstart

```bash
pip install duvo-sandstorm
ds doctor                  # verify creds before running anything
ds init research-brief
cd research-brief
ds "Research Acme's competitors, crawl their sites, write a one-page brief with sources"
```

`ds doctor` is the fastest way to catch a missing `ANTHROPIC_API_KEY` / `E2B_API_KEY` /
Slack scope before your first real query.

## In Slack

```bash
pip install "duvo-sandstorm[slack]"
ds slack setup             # interactive, opens Slack app install in your browser
ds slack start             # Socket Mode (dev), use --http for production
```

Once installed:

- `@Sandstorm review PR 123 in owner/repo`: agent picks up context, runs tests, posts review
- `/remember shipping address is Berlin`: personal memory
- `/team-remember shipping address is Berlin`: workspace-wide memory (v0.9.1)
- `/channel-remember on-call rotation`: channel-scoped memory (v0.9.1)
- `/cancel`: stop the most recent in-flight run in this channel (v0.9.1)
- `/model claude-haiku-4-5-20251001`: per-thread model override
- Reaction triggers: add an emoji to any message to fire an agent (v0.9.1, see [docs/triggers.md](docs/triggers.md))
- App Home tab shows memories, active runs, channel defaults, and triggers (v0.9.1)

Thread continuity is real: each thread keeps its own paused sandbox on the configured runtime,
E2B by default, so uploaded files, generated outputs, and installed packages survive across
messages, even across server restarts. See [docs/memory.md](docs/memory.md).

## Triggers (v0.9.1)

Fire agent runs from cron schedules, inbound webhooks, or Slack reactions:

```json
"triggers": [
  {"name": "standup", "type": "cron", "schedule": "0 9 * * MON-FRI", "prompt": "Post standup"},
  {"name": "issue-triage", "type": "webhook", "path": "/triggers/gh",
   "secret": "${GH_SECRET}", "prompt": "Triage: {{body.issue.title}}"},
  {"name": "summarize-on-robot", "type": "reaction", "emoji": "robot_face",
   "prompt": "Summarize {{message.text}}"}
]
```

Sub-hourly cron supported (Claude Code Routines enforces a 1-hour minimum).
See [docs/triggers.md](docs/triggers.md) and [docs/managed-agents-interop.md](docs/managed-agents-interop.md)
for the MA interop patterns.

## Pick a starter

| Starter             | Use when…                                                       | Aliases |
| ------------------- | --------------------------------------------------------------- | ------- |
| `general-assistant` | One flexible agent for mixed workflows                           |     |
| `research-brief`    | Research a topic, compare options, support a decision            | `competitive-analysis` |
| `document-analyst`  | Review transcripts, reports, PDFs, or decks                      |     |
| `support-triage`    | Triage tickets into priorities, owners, next actions              | `issue-triage` |
| `api-extractor`     | Crawl docs and draft an API summary + OpenAPI spec               | `docs-to-openapi` |
| `security-audit`    | Structured security review with sub-agents and an OWASP skill    |     |
| `code-review`       | Review GitHub PRs with the GitHub MCP, inline comments, CI logs | `pr-review` |

`ds init --list` for the current catalog.

## Add toolpacks

```bash
ds add --list                                   # bundled: linear, notion, firecrawl, exa, github
ds add linear
ds add github
```

For any MCP server not in the bundled catalog, `ds add --custom` wires it in
one command without hand-editing `sandstorm.json` (v0.9.1):

```bash
ds add --custom hubspot --package @hubspot/mcp-server --env PRIVATE_APP_ACCESS_TOKEN
ds add --custom zapier --package mcp-remote --arg https://mcp.zapier.app/mcp --env ZAPIER_MCP_TOKEN
ds add --custom postgres --runtime uvx --package postgres-mcp --env DATABASE_URI
```

See [docs/custom-mcps.md](docs/custom-mcps.md) for npm / mcp-remote / uvx patterns
and the trust-boundary note on running arbitrary MCP packages inside your sandbox.

## Replay a run with a different model

```bash
ds replay <run_id> --model claude-haiku-4-5-20251001 --budget 0.05
```

Forks the original agent session so the replay starts with identical context but on a fresh
branch. A fast, cheap way to A/B compare models or reproduce bug-report runs. Reports
cost Δ, latency Δ, and turn-count Δ as a markdown table. Details in [docs/replay.md](docs/replay.md).

## Install extras

```bash
pip install duvo-sandstorm                    # CLI + server
pip install "duvo-sandstorm[client]"          # Async Python client
pip install "duvo-sandstorm[slack]"           # Slack bot
pip install "duvo-sandstorm[telemetry]"       # OpenTelemetry
```

TypeScript client source lives in [clients/typescript](clients/typescript/README.md) for
repo-local workspace usage. It is not published to npm.

## Deploy

- **Railway**: one-click [template](deploy/railway.json), 30-second deploy
- **Docker**: `Dockerfile` in repo root, `docker-compose.yml` for local
- **Self-host**: `pipx install duvo-sandstorm && ds serve`
- **Langfuse-bundled local stack**: `docker compose -f deploy/docker-compose.langfuse.yml up`

## Docs

- [Getting started](docs/getting-started.md)
- [Comparison vs Managed Agents / Victor / others](docs/comparison.md)
- [When to pick which (FAQ)](docs/faq-vs-managed-agents.md)
- [Multi-LLM: GPT-5, Gemini, DeepSeek, Ollama, self-hosted](docs/multi-llm.md)
- [Observability: Langfuse, Phoenix, Langsmith](docs/observability.md)
- [Memory: `/remember`, `/forget`, persistence guarantees](docs/memory.md)
- [Replay](docs/replay.md)
- [Python client](docs/client.md) · [TypeScript client](clients/typescript/README.md)
- [Configuration](docs/configuration.md) · [API reference](docs/api.md)
- [Slack bot](docs/slack.md) · [Deployment](docs/deployment.md) · [OpenRouter](docs/openrouter.md)

## Community

If Sandstorm closes a gap for you, [star the repo](https://github.com/tomascupr/sandstorm)
and [open an issue](https://github.com/tomascupr/sandstorm/issues) or
[discussion](https://github.com/tomascupr/sandstorm/discussions) with your use case.
We read every one.
