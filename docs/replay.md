# Replay

`ds replay <run_id>` re-executes a prior run. It is the fast, cheap way to
A/B compare models, tighten a budget on an expensive prompt, or reproduce a
bug-report run after a fix has landed.

## How it works

Every run recorded by sandstorm carries the raw prompt, a snapshot of its
config (model, allowed tools, files, MCP servers), and the Agent SDK session
ID returned by the runner. `ds replay` rebuilds a `QueryRequest` from that
snapshot, applies your overrides, and ships it back into the sandbox.

When the original run has a session ID, the replay passes `resume=<id>` plus
`forkSession=True` to the Agent SDK. The new run starts with the original
transcript in context but branches off at that point, so the model does not
redo its preamble work.

## Basic usage

```bash
ds replay abc12345 --model claude-haiku-4-5-20251001 --budget 0.05
```

Available flags:

| Flag               | Effect                                                                 |
| ------------------ | ---------------------------------------------------------------------- |
| `--model`          | Override the model for the replay.                                     |
| `--budget`         | Hard cap on cost in USD. Passes `maxBudgetUsd` to the Agent SDK.       |
| `--allowed-tools`  | Comma-separated tool whitelist override (`Read,Bash,Write`).           |
| `--output`         | Write the diff report to a file instead of stderr.                     |
| `--json-output`    | Stream raw JSON events to stdout (useful for pipelines).               |
| `--anthropic-api-key` / `--e2b-api-key` / `--openrouter-api-key` | Override the resolved provider credentials for this replay. |

## Report

On completion, `ds replay` emits a markdown table comparing the replay to
the original:

```
# Replay report: abc12345 → replay-1f9e

| Metric       | Original              | Replay                | Δ |
| ------------ | --------------------- | --------------------- | -- |
| Model        | claude-opus-4-7       | claude-haiku-4-5-20251001 | — |
| Cost (USD)   | 0.15                  | 0.0084                | ↓ -0.1416 (-94.4%) |
| Turns        | 8                     | 7                     | ↓ -1 (-12.5%) |
| Duration (s) | 42.0                  | 18.3                  | ↓ -23.7 (-56.4%) |
| Budget cap   | n/a                   | $0.05                  | — |

> Forked session: yes
```

## Finding `run_id`

- From Slack: each assistant reply has a footer showing `Run: <id>`.
- From the CLI: the dashboard at `/runs` lists recent runs newest-first.
- From the Python client: `client.list_runs()` returns the same data.

Pre-v0.9 runs without a captured `agent_session_id` still replay. They run
from scratch instead of forking; the report shows `Forked session: no prior
session_id saved`.

## Storage

Runs (and replay records) live in `.sandstorm/runs.jsonl`. The file is
append-only with tombstones, so it grows slowly. The in-memory `RunStore`
deque holds the 200 most recent by default.

## Caveats

- Replays share the same provider credentials as the original unless you
  override them. If the original used OpenRouter, the replay will too.
- File uploads are snapshotted only by name, not by content. If you replay
  a run that used `-f data.csv`, sandstorm will try to re-upload whatever
  `data.csv` is on disk now, which may not match the original.
- `fork_session` depends on the Agent SDK version. The bundled 0.2.112 SDK
  supports it; older sandboxes fall back to full re-execution.
