# Triggers

Triggers fire agent runs from three sources without a human typing in Slack or
running `ds` on their laptop. Configure them in `sandstorm.json` under the
`triggers` array.

Three types:

1. **cron**: a schedule that fires at regular intervals. Supports sub-hourly
   ("every minute" works). Useful for daily digests, hourly pulls, weekly
   reviews.
2. **webhook**: a public HTTP endpoint that fires when something calls it.
   Useful for "when a GitHub issue opens, triage it" or "when Managed Agents
   signals session.status_idled, take the next step."
3. **reaction**: an emoji reaction on a Slack message fires the agent with the
   message as context. Useful for "react :robot_face: to summarise any
   message."

## Security first (read this before deploying webhooks)

Webhook triggers mount a public `POST /triggers/<path>` endpoint on the
Sandstorm server. Anything with the URL can fire the trigger unless you
configure a secret.

Always set a `secret`:

```json
{
  "name": "github-issue-triage",
  "type": "webhook",
  "path": "/triggers/github-issue",
  "secret": "${GITHUB_WEBHOOK_SECRET}",
  "prompt": "Triage: {{body.issue.title}}"
}
```

Callers must send `X-Sandstorm-Trigger-Secret: <secret>`. Constant-time
comparison; wrong or missing header returns HTTP 401.

If you omit `secret`, Sandstorm logs a warning on startup and the endpoint
accepts any unauthenticated POST. Don't expose that to the public internet.

## Cron examples

```json
"triggers": [
  {
    "name": "daily-standup",
    "type": "cron",
    "schedule": "0 9 * * MON-FRI",
    "prompt": "Post today's standup summary to #eng"
  },
  {
    "name": "hourly-support-digest",
    "type": "cron",
    "schedule": "0 * * * *",
    "prompt": "Summarise any new support tickets from the last hour"
  },
  {
    "name": "minute-heartbeat",
    "type": "cron",
    "schedule": "* * * * *",
    "prompt": "Heartbeat"
  }
]
```

Sub-hourly is supported. Managed Agents' Routines product enforces a 1-hour
minimum; Sandstorm goes down to `* * * * *`.

## Webhook examples

### Generic JSON payload

```json
{
  "name": "github-issue",
  "type": "webhook",
  "path": "/triggers/github-issue",
  "secret": "${GH_WEBHOOK_SECRET}",
  "prompt": "Triage: {{body.issue.title}}\n\n{{body.issue.body}}"
}
```

Fire it:

```bash
curl -X POST https://your-host/triggers/github-issue \
  -H "X-Sandstorm-Trigger-Secret: $GH_WEBHOOK_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"issue": {"title": "Login broken", "body": "Users see 500 on /login"}}'
```

### Managed Agents interop

Point Managed Agents' `session.status_idled` webhook at Sandstorm:

```json
{
  "name": "ma-session-idle-handler",
  "type": "webhook",
  "path": "/triggers/ma-idle",
  "secret": "${MA_WEBHOOK_SECRET}",
  "prompt": "MA session {{body.session_id}} went idle with status {{body.status}}. Review its output and post a summary."
}
```

See `docs/managed-agents-interop.md` for the full pattern.

## Reaction examples

```json
{
  "name": "summarize-on-robot",
  "type": "reaction",
  "emoji": "robot_face",
  "channels": ["C0123456"],
  "prompt": "Summarize the reacted message:\n\n{{message.text}}"
}
```

- `emoji`: Slack shortcode without colons (`robot_face`, not `:robot_face:`).
- `channels`: optional whitelist. Omit to match the emoji in any channel the
  bot is in.
- The reacted-to message is fetched via `conversations.history` and exposed
  as `{{message.text}}`, `{{message.user}}`, `{{channel.id}}`, `{{reaction}}`.

Requires the `reactions:read` scope in your Slack app manifest. v0.9.1 adds
it; users upgrading from v0.9.0 need one reinstall to pick up all v0.9.1
scope additions.

## Prompt templates

Placeholders use `{{source.path.to.value}}` and resolve against whichever
sources are available for that trigger type:

| Trigger | Available sources |
| ------- | ----------------- |
| cron    | (none) |
| webhook | `body.*`, `headers.*` |
| reaction | `message.*`, `channel.*`, `reaction` |

Missing keys render as empty strings. No Jinja, no eval, no code execution.

## CLI

- `ds trigger list`: show all configured triggers with next-fire time for
  cron, secret status for webhooks, and emoji+channels for reactions.
- `ds trigger test <name>`: fire a trigger by name on demand. Skips webhook
  secret verification so you can test locally.

## Limits and caveats

- v0.9.1 triggers are fire-and-forget. A cron instant missed while the
  server is down is not replayed. Durable queues and retry semantics land
  in v0.10.
- Webhook triggers return HTTP 202 (accepted) and run the agent
  asynchronously. If you need a synchronous response, call `POST /query`
  directly instead.
- Cron and reaction triggers do not carry files. Webhook triggers do not
  upload the POST body as a file; use the prompt template to include what
  you need.
