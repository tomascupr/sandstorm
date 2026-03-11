# Getting started

Sandstorm gives you a fast path from install to a runnable agent project.

## Quick start

```bash
pip install duvo-sandstorm
ds init
cd general-assistant
ds add linear
ds "Compare Notion, Coda, and Slite for async product teams"
```

## Install extras

Use the base package for the CLI and server:

```bash
pip install duvo-sandstorm
```

Add extras only for the surfaces you need:

```bash
pip install "duvo-sandstorm[client]"      # Async Python client
pip install "duvo-sandstorm[slack]"       # Slack bot support
pip install "duvo-sandstorm[telemetry]"   # OpenTelemetry integration
```

The guided `ds init` flow scaffolds:

- `sandstorm.json`
- `README.md`
- `.env.example`
- starter-specific assets such as `.claude/skills/...` when needed

If `ANTHROPIC_API_KEY` or `E2B_API_KEY` are missing, the guided flow prompts for them and writes
`.env` so the starter runs immediately.

## Prerequisites

- Python 3.11+
- An [E2B](https://e2b.dev) API key
- An [Anthropic](https://console.anthropic.com) API key, or an alternate provider configured through [OpenRouter](openrouter.md) or the provider env vars in [configuration](configuration.md)
- `uv` only if you want a source checkout workflow

## Starter commands

```bash
ds init
ds init --list
ds init research-brief
ds init security-audit my-audit
ds init support-triage --force
```

Behavior:

- `ds init` opens the guided flow
- `ds init <starter>` scaffolds into `./<starter-slug>`
- `ds init <starter> <directory>` scaffolds directly into the provided directory
- `--force` overwrites starter-managed files in an existing destination

## Add a bundled toolpack

Install bundled MCP integrations into the current project:

```bash
ds add --list              # Show all available toolpacks
ds add linear              # Issue tracking via Linear
ds add notion              # Knowledge base via Notion
ds add firecrawl           # Web scraping via Firecrawl
ds add exa                 # AI-powered search via Exa
ds add github              # GitHub repos, issues, and PRs
```

Each command updates the current project's `sandstorm.json`, prompts for the required API key when
needed, writes it to `.env`, and adds a placeholder to `.env.example`.

Behavior:

- `ds add --list` shows bundled toolpacks plus whether each one is installed, not installed, or customized
- `ds add <toolpack>` updates `sandstorm.json`, `.env`, and `.env.example` for the current project
- If the project already defines a different MCP server block for that toolpack, the command stops
- `ds add <toolpack> --force` replaces that toolpack's MCP server config and keeps other servers untouched

## Run one-off queries

The default CLI command is `query`, so you can pass a prompt directly:

```bash
ds "Compare Vercel, Netlify, and Cloudflare Pages for a startup team"
ds "Create a content brief for AI support automation" --model opus
ds query "Summarize this PDF and list the key risks"
```

## Upload files

Use `-f` / `--file` to send local text files into the sandbox:

```bash
ds "Analyze this CSV and find outliers" -f data.csv
ds "Compare these configs" -f prod.json -f staging.json
ds "Summarize this transcript" -f notes.txt
```

Files are uploaded to `/home/user/{filename}` before the agent starts. The CLI accepts text files.
For binary uploads such as PDFs, DOCX, images, audio, or video, use the [API](api.md) or [Slack](slack.md).

## Start the server

```bash
ds serve
ds serve --port 3000
ds serve --reload
```

The server exposes:

- `POST /query` for streaming agent execution
- `GET /runs` for recent run history
- `GET /health` for liveness and optional deep checks
- `GET /` for the built-in dashboard

## Dashboard

Start the server and open `http://localhost:8000/` to inspect recent runs:

```bash
ds serve
open http://localhost:8000
```

The dashboard shows status, model, cost, turns, and duration for runs handled by that process.
History is stored in `.sandstorm/runs.jsonl` and survives server restarts on the same machine.
When `SANDSTORM_API_KEY` is set, `/runs` requires a bearer token and the built-in dashboard shows
an auth-required message instead of run data.

## Python client

If you want to call Sandstorm from your own application, install the `client` extra and use the
[Python client guide](client.md).

## Source install

```bash
git clone https://github.com/tomascupr/sandstorm.git
cd sandstorm
uv sync --extra dev
ds init
```

## Runtime model

Each request follows the same basic path:

1. Sandstorm creates a fresh E2B sandbox.
2. It uploads your config, prompt, and any files.
3. The Claude Agent SDK runs inside the sandbox with the configured tools.
4. Sandstorm streams events back over CLI, API, or Slack.
5. The sandbox is destroyed when the task finishes.
