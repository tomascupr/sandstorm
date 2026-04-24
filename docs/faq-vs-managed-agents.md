# When to pick Sandstorm vs the alternatives

Short decision guide. If you recognize your constraint on the left, the right
column tells you which way to go.

## Picking the runtime

| Your constraint                                             | Pick                                     |
| ----------------------------------------------------------- | ---------------------------------------- |
| Zero-infra, Claude-only, no data-residency concerns         | **Claude Managed Agents**                |
| You live in TypeScript and deploy to Vercel                 | **Vercel Slack Agent Skill + Chat SDK**  |
| Data must stay on your network (VPC, on-prem, EU-only)      | **Sandstorm**                            |
| You need GPT-5 / Gemini / DeepSeek / Qwen / Grok / Kimi     | **Sandstorm**                            |
| You need Bedrock / Vertex / Azure Foundry                   | **Sandstorm**                            |
| You want traces in Langfuse / Phoenix / Langsmith           | **Sandstorm**                            |
| You want a Slack bot that ships with the framework          | **Sandstorm** or Vercel Slack Agent      |
| You want one agent per laptop (personal automation)         | **claude-code-slack-bot** family         |
| You want `ds replay` / run archive / session fork out of the box | **Sandstorm**                       |

## Can I migrate between them?

- **From Managed Agents → Sandstorm:** swap the Anthropic endpoint for your
  own `ds serve`; drop MCP server configs into `sandstorm.json`; the prompts,
  tools, and skills transfer as-is.
- **From Vercel Slack Agent → Sandstorm:** the Slack manifest is close;
  replace the Next.js handler with a `ds slack start`; the Agent SDK options
  map 1:1 because both use the same SDK under the hood.
- **From Sandstorm → Managed Agents:** drop the sandbox layer and point the
  Agent SDK at Anthropic's managed endpoint. You lose replay + memory +
  per-thread pause.

## What if my situation changes?

All three are layers on the same Agent SDK. If you start self-hosted and
later want to move to Managed Agents, your prompts, tools, skills, and
session IDs transfer. Sandstorm is explicitly designed not to be a trap, none of the positioning wedges (self-host, multi-provider, OTel) rely on
proprietary file formats.

## What Sandstorm is not

- Not a hosted SaaS (today). There's no `sandstorm.cloud` tier, deploy it
  yourself. See the [deployment guide](deployment.md) for paths.
- Not a Langchain / LangGraph / CrewAI competitor. It uses the Claude Agent
  SDK for orchestration and focuses on the runtime + Slack + memory + replay
  layer above it.
- Not a computer-use agent (that's E2B Surf or the Claude Computer Use tool).
  Sandstorm runs the Agent SDK in a sandboxed Linux environment with tool
  access, not a virtual desktop.
