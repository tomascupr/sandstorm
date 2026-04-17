# Memory

Sandstorm gives each user a small, durable memory that the agent sees as
part of its system prompt on every run. Users manage it with slash commands
in Slack; CLI/HTTP runs can write to it via the `remember` field on
`QueryRequest`.

Design principle: the agent does not decide when to use memory. The host
always injects it. This sidesteps the "agent forgot to call the memory tool"
class of bug that plagues tool-based memory systems.

## Three scopes (v0.9.1+)

Memories live in one of three scopes. The agent sees all three concatenated
in the system prompt, most-general first:

- **team**: shared across everyone in the Slack tenant
  (the workspace, or enterprise for Grid installs)
- **channel**: shared across users in a specific Slack channel
- **user**: personal to one user in one tenant (v0.9.0 default)

## Slash commands (Slack)

| Command                              | Effect                                                                 |
| ------------------------------------ | ---------------------------------------------------------------------- |
| `/remember <fact>`                   | Persist a personal fact for you (user scope).                          |
| `/team-remember <fact>`              | Shared across everyone in this workspace (team scope).                 |
| `/channel-remember <fact>`           | Shared within this channel only (channel scope).                       |
| `/forget <substring> [scope]`        | Delete memories containing the substring. Optional scope filter.       |
| `/memories [scope]`                  | List what Sandstorm remembers. Default: combined view (team + channel + user). |

Examples:

```
/remember my shipping address is Berlin, Germany
/remember preferred Postgres flavour is Aurora
/forget Aurora
/memories
```

## CLI / HTTP

On the `QueryRequest`:

```python
{
  "prompt": "...",
  "team_id": "T_ABC",
  "user_id": "U_XYZ",
  "remember": "prefers tabs over spaces"
}
```

When `remember` is set, Sandstorm writes it to the memory store before
dispatching the run. Leaving `team_id` / `user_id` unset scopes memory to
a local default (`__local__`), which is what `ds "..."` uses.

## What the agent sees

At query time, the builder prepends your memories as bullets to
`system_prompt_append`:

```
User memory (persisted across sessions):
- my shipping address is Berlin, Germany
- preferred Postgres flavour is Aurora

<your project's system_prompt_append follows>
```

This happens before the project-level append so project conventions stay
closest to the prompt (highest-precedence instruction).

## Scope

Memories are keyed on `(team_id, user_id)`. There is no cross-workspace
sharing and no "global" memory. A Slack user in workspace A cannot read
what the same agent remembers about a user in workspace B.

For CLI/HTTP runs without Slack context, both keys default to `__local__`.
Effectively a single-user memory pool per deployment.

## Storage

JSONL at `.sandstorm/memories.jsonl`, mirroring the `RunStore` shape.
Deletes are tombstone records rather than in-place mutations, so the
history is never lost, only hidden at load time.

File format:

```jsonl
{"id":"abc","team_id":"T1","user_id":"U1","text":"likes oat milk","created_at":"2026-04-17T13:00:00+00:00","deleted":false}
{"id":"abc","team_id":"T1","user_id":"U1","text":"likes oat milk","created_at":"2026-04-17T13:00:00+00:00","deleted":true}
```

Two rows, same `id`: the second row tombstones the first.

## Sizing

Default `maxlen` is 10,000 entries across all users in the deployment. Old
entries get evicted FIFO when the limit is hit. For a single-workspace
deployment with tens of users, this is effectively unbounded. If you need
more, construct a `MemoryStore` with a larger `maxlen` in your own entry
point.

## What memory does not do

- It is not a vector store. No semantic search. The entire memory list goes
  into the prompt each run (truncated by the model's context window if it
  ever gets huge, which it will not at JSONL sizes).
- It does not persist across sandboxes beyond a single thread (each run gets
  a fresh sandbox; memory is a host-side artifact).
- It does not share between CLI runs and Slack runs unless you pass the
  same `team_id` / `user_id` on the CLI request.
- It is not the Claude Agent SDK session archive. Session-level continuity
  lives in [replay](replay.md) and Slack thread resume, which are separate.
