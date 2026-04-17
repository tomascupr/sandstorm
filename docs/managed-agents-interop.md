# Managed Agents interop

Anthropic's Claude Managed Agents (launched April 8, 2026) solve a different
part of the agent-orchestration problem than Sandstorm. The two products are
complementary, not competitive. This page explains where each one fits and
how to wire them together.

## What Managed Agents does

- Runs Claude inside an Anthropic-operated sandbox with bash / file / web
  tools and MCP access
- Bills session runtime at $0.08 per session-hour (idle time not billed)
- Emits webhook callbacks on `session.status_idled` and similar lifecycle
  events
- Requires the `managed-agents-2026-04-01` beta header

What it does **not** ship:

- A built-in scheduler. Users fire sessions from their own code.
- A Slack bot. Anthropic's Cookbook has a Bolt-Python recipe, but the
  user wires it themselves.
- Multi-provider support. Claude models only; no OpenRouter, Bedrock,
  Vertex, etc.

## What Sandstorm adds

- **A scheduler**: cron (sub-hourly, unlike Claude Code Routines' 1-hour
  minimum) that can fire Managed Agents sessions or run agents in your
  own E2B sandbox
- **A Slack bot**: @mentions, DMs, slash commands, App Home, pause/resume
  per-thread sandboxes
- **Multi-provider**: Anthropic, OpenRouter, Vertex, Bedrock, Azure
  Foundry, and any OpenAI-compatible base URL
- **Self-hosted**: your infra, your data, your observability

## Two interop patterns

### Pattern A: MA fires, Sandstorm reacts

Use this when a Managed Agents session finishes and you want Sandstorm to
take the next step (post a summary to Slack, trigger a follow-up task,
update a ticket, etc.).

1. Configure a Sandstorm webhook trigger:

   ```json
   {
     "name": "ma-session-idle",
     "type": "webhook",
     "path": "/triggers/ma-idle",
     "secret": "${MA_WEBHOOK_SECRET}",
     "prompt": "Managed Agents session {{body.session_id}} finished with status {{body.status}}. Review its final output, post a summary to #eng, and flag anything that needs follow-up."
   }
   ```

2. Register Sandstorm's URL as the `webhook_url` on the MA session with the
   matching `secret`:

   ```
   POST https://api.anthropic.com/v1/sessions
   anthropic-beta: managed-agents-2026-04-01
   {
     "webhook_url": "https://your-sandstorm-host.example/triggers/ma-idle",
     "webhook_secret": "<same as MA_WEBHOOK_SECRET>",
     ...
   }
   ```

   MA calls your endpoint with the `X-Sandstorm-Trigger-Secret` header and
   a JSON body containing `session_id` / `status` / other session metadata.

3. Sandstorm fires the agent run with the substituted prompt. The run
   lands in `run_store` so it shows up in the dashboard and App Home.

### Pattern B: Sandstorm fires, MA handles

Use this when Sandstorm's scheduler or a Slack interaction should kick off
an MA session (for example: a cron trigger that spins up a long-running
MA analysis agent on a schedule MA can't schedule itself).

1. Add a Sandstorm cron trigger:

   ```json
   {
     "name": "weekly-ma-review",
     "type": "cron",
     "schedule": "0 9 * * MON",
     "prompt": "Start a Managed Agents session to review last week's production logs and file any incidents as GitHub issues."
   }
   ```

2. Give the Sandstorm agent MCP access to the Anthropic API (or a
   pre-built MCP server wrapper) so it can call `POST /v1/sessions` to
   spin up an MA session with whatever configuration it needs.

3. The Sandstorm run records the MA session id in its final output so
   you can correlate the two runs in dashboards.

## Sub-hourly cron

Claude Code Routines (a separate Anthropic product) caps cron schedules
at a 1-hour minimum interval. Sandstorm supports sub-hourly down to
`* * * * *`. If you need minute-level scheduling for agent work and want
to stay self-hosted, use Sandstorm.

## Migrating from the Anthropic Slack cookbook recipe

If you followed the [Claude Managed Agents Slack data bot](
https://platform.claude.com/cookbook/managed-agents-slack-data-bot) recipe,
here's the direct Sandstorm equivalent:

| Recipe step | Sandstorm equivalent |
| ----------- | -------------------- |
| `pip install slack-bolt anthropic` | `pip install "duvo-sandstorm[slack]"` |
| Hand-roll a Bolt app with `@app.event("app_mention")` | Already wired; run `ds slack setup` |
| Thread a CMA session through `anthropic.beta.sessions.create` | Set `"model": "sonnet"` in `sandstorm.json`; agent runs in your E2B sandbox |
| Wire file upload | Already wired (see `_download_thread_files`) |
| Wire feedback UI | Already wired (feedback buttons in the metadata footer) |
| Redeploy to update prompts | Edit `sandstorm.json`; the next run picks up changes without a restart |

The Cookbook recipe is a good reference for MA semantics but requires you
to own the Slack-bot plumbing. Sandstorm ships that plumbing.

## When to pick which

Pick Managed Agents when:
- You want Claude-only, Anthropic-hosted, zero-infra.
- You don't need multi-provider routing.
- You're comfortable paying per-session-hour.
- You'll wire your own scheduler and Slack bot.

Pick Sandstorm when:
- You need self-hosted, multi-provider, or data-residency control.
- You want Slack native out of the box.
- You need sub-hourly scheduling for agent work.
- You want to own your observability surface (OpenTelemetry to any
  backend).

Pick both when:
- You want MA's managed sandbox for specific workloads but Sandstorm's
  scheduler + Slack for everyday agent work.
- Set up the interop patterns above. They work today.
