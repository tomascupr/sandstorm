# Configuration

Sandstorm uses a two-layer model:

| Layer | What it controls | How to set it |
|-------|------------------|---------------|
| `sandstorm.json` | Default agent behavior for a project | Config file in the project root |
| API request | Per-run overrides | JSON body on `POST /query` |

## `sandstorm.json`

Drop a `sandstorm.json` file in your project root.

| Field | Type | Description |
|-------|------|-------------|
| `system_prompt` | `string` or `object` | Base instructions for the agent |
| `system_prompt_append` | `string` | Extra instructions appended after the base prompt |
| `model` | `string` | Default model such as `sonnet`, `opus`, `haiku`, or a full model ID |
| `max_turns` | `integer` | Maximum conversation turns |
| `timeout` | `integer` | Sandbox lifetime in seconds |
| `output_format` | `object` | JSON schema for structured output |
| `agents` | `object` | Named sub-agent definitions |
| `mcp_servers` | `object` | MCP server configuration |
| `skills_dir` | `string` | Directory containing Claude Code skills |
| `allowed_tools` | `string[]` | Restrict the runtime to a subset of tools |
| `template_skills` | `boolean` | Set `true` when required skills are already baked into the sandbox template |
| `webhook_url` | `string` | Public URL for E2B lifecycle webhooks |

## Recommended customization model

For starter projects, keep the base instructions in `system_prompt` and put team-specific steering
in `system_prompt_append`. This keeps the starter readable and makes local customization obvious.

Example:

```json
{
  "system_prompt": "You are a research analyst. Compare options and return a concise brief.",
  "system_prompt_append": "Use our tone: direct, practical, and skeptical of vendor claims."
}
```

## Structured output

Use `output_format` when you want the runtime to return validated JSON instead of free-form text.

```json
{
  "output_format": {
    "type": "json_schema",
    "schema": {
      "type": "object",
      "properties": {
        "summary": { "type": "string" },
        "items": {
          "type": "array",
          "items": { "type": "string" }
        }
      },
      "required": ["summary", "items"]
    }
  }
}
```

The final structured output is returned in the `result.structured_output` payload.

## Sub-agents

Use `agents` to define specialists that the main agent can delegate to through the `Task` tool.
This is separate from MCP integrations: external tool servers belong under `mcp_servers`, not
`agents`.

```json
{
  "agents": {
    "scraper": {
      "description": "Crawls websites and saves structured data to disk.",
      "prompt": "Scrape the target, extract the useful data, and save it to /home/user/output/.",
      "tools": ["Bash", "WebFetch", "Write", "Read"],
      "model": "sonnet"
    }
  }
}
```

## Skills

Sandstorm supports [Claude Code Skills](https://docs.anthropic.com/en/docs/claude-code/skills).

- Point `skills_dir` at a directory of skill folders with `SKILL.md`
- Use `template_skills: true` when the skills are already baked into the sandbox image
- When skills are present, Sandstorm automatically adds the `Skill` tool if `allowed_tools` comes from config

Example:

```json
{
  "skills_dir": ".claude/skills",
  "allowed_tools": ["Read", "Glob", "Grep", "Bash"]
}
```

The default sandbox template already includes document-processing skills for PDF, DOCX, and PPTX workflows.

## MCP servers

Attach external tools with [Model Context Protocol](https://modelcontextprotocol.io):

```json
{
  "mcp_servers": {
    "linear": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-linear"],
      "env": {
        "LINEAR_API_KEY": "${LINEAR_API_KEY}"
      }
    }
  }
}
```

If you want a bundled integration, use the CLI instead of editing JSON by hand:

```bash
ds add --list              # Show all available toolpacks
ds add linear              # Issue tracking via Linear
ds add notion              # Knowledge base via Notion
ds add firecrawl           # Web scraping via Firecrawl
ds add exa                 # AI-powered search via Exa
ds add github              # GitHub repos, issues, and PRs
```

`ds add` writes the MCP server entry into `sandstorm.json` for the current project and updates the
required env vars in `.env` / `.env.example`.

If the current project already defines a different MCP server block for that toolpack, `ds add`
stops instead of overwriting it. Re-run with `--force` to replace only that MCP server entry.

Use request-level whitelists such as `allowed_mcp_servers` to expose only a subset on a given call.

Sandstorm resolves environment placeholders inside `mcp_servers` before the agent run starts.
Supported forms:

- `${VAR_NAME}` for required env vars
- `${VAR_NAME:-default}` for defaults when the host env var is unset

This placeholder resolution applies to string values anywhere inside an MCP server config, such as
`command`, `args`, `env`, `url`, and `headers`.

## Providers

Sandstorm supports Anthropic by default plus OpenRouter, Vertex AI, Bedrock, Azure Foundry, and custom proxies.

| Provider | Key env vars |
|----------|--------------|
| Anthropic | `ANTHROPIC_API_KEY` |
| OpenRouter | `ANTHROPIC_BASE_URL`, `OPENROUTER_API_KEY`, optional `ANTHROPIC_DEFAULT_*_MODEL` |
| Vertex AI | `CLAUDE_CODE_USE_VERTEX=1`, `CLOUD_ML_REGION`, `ANTHROPIC_VERTEX_PROJECT_ID`, `GOOGLE_APPLICATION_CREDENTIALS` |
| Bedrock | `CLAUDE_CODE_USE_BEDROCK=1`, `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` |
| Azure Foundry | `CLAUDE_CODE_USE_FOUNDRY=1`, `AZURE_FOUNDRY_RESOURCE`, `AZURE_API_KEY` |
| Custom proxy | `ANTHROPIC_BASE_URL`, optional `ANTHROPIC_AUTH_TOKEN` |

For OpenRouter specifics, see the dedicated [OpenRouter guide](openrouter.md).

## Webhooks

Set `webhook_url` in `sandstorm.json` to receive E2B sandbox lifecycle events:

```json
{
  "webhook_url": "https://your-server.com/webhooks/e2b"
}
```

When this field is configured, Sandstorm registers the webhook on server startup and deregisters it on shutdown.

You can also manage webhooks from the CLI:

```bash
ds webhook register https://your-server.com
ds webhook list
ds webhook test https://your-server.com/webhooks/e2b
```
