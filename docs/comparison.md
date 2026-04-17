# Sandstorm vs the closed alternatives

This is the detailed version of the comparison table in the README. All claims
here are structural, things that cannot easily change without a new product
launch from the other side.

## vs Claude Managed Agents (Anthropic: April 2026)

Managed Agents is a hosted product that runs Claude agents in Anthropic-operated
sandboxes. It's excellent when you want the fastest path from API key to a
running agent and you're happy to stay on Anthropic's infra and model.

Where Sandstorm differs:

| Axis                        | Sandstorm                                          | Managed Agents                           |
| --------------------------- | -------------------------------------------------- | ---------------------------------------- |
| Runtime location            | Your infra (Railway / Fly / K8s / Docker / laptop) | Anthropic's infra only                   |
| Models                      | Anthropic, OpenRouter, Vertex, Bedrock, Azure, any OpenAI-compatible base URL | Claude only                              |
| Sandbox provider            | E2B (self-host or hosted)                          | Anthropic-operated                       |
| Chat integration            | Slack bot in the repo                              | No chat wrappers                         |
| Data flow                   | Everything stays in your network                   | Runtime traffic goes through Anthropic   |
| Observability               | OTel → Langfuse / Phoenix / Langsmith / any OTLP   | Anthropic console only                   |
| Pricing model               | Your Claude/OpenRouter/E2B bills                   | Token rates + $0.08/session-hour active  |
| License                     | MIT                                                | Proprietary SaaS                         |

**Pick Managed Agents when:** you want zero-infra, you're Anthropic-only, and
data residency isn't a concern.

**Pick Sandstorm when:** you need self-host, multiple model providers, Slack
out of the box, or your observability stack is not Anthropic's.

## vs Vercel Slack Agent Skill + Chat SDK (March 2026)

Vercel's pitch: `npx skills add vercel-labs/slack-agent-skill` then drive the
wizard from Claude Code or Cursor. Good templates, fast path to a Slack agent.

Where Sandstorm differs:

| Axis                       | Sandstorm                              | Vercel Slack Agent Skill               |
| -------------------------- | -------------------------------------- | -------------------------------------- |
| Language                   | Python (FastAPI)                       | TypeScript (Next.js)                   |
| Deploy target              | Anywhere that runs Python              | Tight Vercel + Workflow DevKit coupling |
| Sandbox                    | E2B (per-thread, paused between messages) | Vercel Sandbox                          |
| Observability              | OTel to any backend                    | Vercel-native                           |
| Replay & run archive       | Built in. `ds replay <run_id>`        | Not part of the template               |
| Memory                     | JSONL, per (team_id, user_id)          | DIY                                    |
| OSS license                | MIT                                    | Apache templates, product-tied runtime |

**Pick Vercel Slack Agent Skill when:** you're already on Vercel, your team
lives in TypeScript, and you want managed durable execution via Workflow
DevKit.

**Pick Sandstorm when:** you want a Python stack, you need to run on
infrastructure Vercel doesn't manage, or you want replay + memory as
first-class features.

## vs claude-code-slack-bot and friends (community projects)

The cluster of OSS repos that run Claude Code in Slack
(`mpociot/claude-code-slack-bot`, `dbenn8/claude-slack`, `41fred/claude-code-slack`,
`lucidash/claude-slack-bridge`) all share one architectural decision: **Claude
runs locally on the maintainer's machine or a dedicated daemon**, not in an
isolated sandbox. That's fine for personal use; it's a non-starter for teams.

Where Sandstorm differs:

| Axis                       | Sandstorm                         | Local-daemon Slack bots        |
| -------------------------- | --------------------------------- | ------------------------------ |
| Where the agent runs       | Fresh E2B sandbox per thread      | Your laptop / a single daemon  |
| Blast radius of a bad prompt | Sandboxed, tear down or pause   | Whatever that laptop can reach |
| Multi-user concurrency     | Per-thread sandbox pool           | Serialized via one process     |
| Production deployment      | Docker / Railway / self-host      | "Keep my laptop on"            |

**Pick a local-daemon bot when:** it's one user, one laptop, personal use only.

**Pick Sandstorm when:** a team depends on it.

## Structural moats, things the closed alternatives can't ship without rebuilding

1. **Your infrastructure, your data.** Managed Agents can add more features but
   can't move Anthropic's runtime into your VPC. Vercel's stack requires Vercel.
2. **Any LLM.** Managed Agents is Claude-only by design. Sandstorm runs whatever
   the Agent SDK's base URL + auth model accepts, that's most of the frontier.
3. **Open observability surface.** Both closed products emit to their own consoles.
   Sandstorm emits OTLP, point it anywhere.

Those three are why "self-hosted, multi-provider, observable" is the structural
Sandstorm pitch. Everything else (memory, replay, per-thread pause) is a feature
that the closed products could ship tomorrow if they chose to.
