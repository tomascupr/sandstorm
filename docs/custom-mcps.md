# Custom MCP servers with `ds add --custom`

Bundled toolpacks (Linear, Notion, Firecrawl, Exa, GitHub) cover the common
cases. For anything else, `ds add --custom` wires an arbitrary MCP server
into your Sandstorm project in one command instead of hand-editing
`sandstorm.json`.

The MCP ecosystem is large (Salesforce's AgentExchange listed 1000+ servers
at TDX 2026). One feature that scales beats one toolpack definition per
release.

## CLI

```
ds add --custom <slug> \
  --package <npm-or-uvx-package> \
  [--runtime npx|uvx] \
  [--env VAR ...] \
  [--arg VALUE ...] \
  [--force]
```

Flags:

- `--custom <slug>`: name the entry under `mcp_servers` in `sandstorm.json`
- `--package <name>`: npm package (default) or uvx package
- `--runtime {npx,uvx}`: default `npx`
- `--env VAR` (repeatable): env var the server expects; added to
  `.env.example` with a placeholder value
- `--arg VALUE` (repeatable): extra positional arg passed after the package
  (for `mcp-remote <url>`-style invocations)
- `--force`: overwrite if the slug already exists with a different config

Re-running is idempotent.

## Three common patterns

### npm package with env auth

```bash
ds add --custom hubspot \
  --package @hubspot/mcp-server \
  --env PRIVATE_APP_ACCESS_TOKEN
```

Produces this entry in `sandstorm.json`:

```json
"mcp_servers": {
  "hubspot": {
    "command": "npx",
    "args": ["-y", "@hubspot/mcp-server"],
    "env": {"PRIVATE_APP_ACCESS_TOKEN": "${PRIVATE_APP_ACCESS_TOKEN}"}
  }
}
```

And adds `PRIVATE_APP_ACCESS_TOKEN=` to `.env.example`.

### Hosted MCP server via `mcp-remote`

For servers that live behind a hosted URL (Zapier's hosted MCP endpoint is
one example), use `mcp-remote` plus a URL argument:

```bash
ds add --custom zapier \
  --package mcp-remote \
  --arg https://mcp.zapier.app/mcp \
  --env ZAPIER_MCP_TOKEN
```

### Python package via uvx

For MCP servers published on PyPI rather than npm (like `crystaldba/postgres-mcp`):

```bash
ds add --custom postgres \
  --runtime uvx \
  --package postgres-mcp \
  --env DATABASE_URI
```

uvx will fetch + run the package on demand. Make sure your deployment has
`uv` installed (it ships with the Sandstorm container image).

## Trust boundary

`sandstorm.json` controls which MCP servers spin up inside your configured sandbox runtime.
A malicious or buggy MCP package has the same access to the sandbox environment as the agent
does: filesystem, network (subject to the runtime provider's policies), and whatever env vars
you pass through.

Treat `ds add --custom <untrusted-package>` like `pip install` from an
untrusted source. In practice:

- Prefer well-known first-party MCPs (HubSpot, Notion, Linear, etc.) where
  the vendor publishes the package.
- For community packages, read the source before wiring them.
- For maximum isolation, scope the agent's `allowed_tools` so it can only
  call the MCP tools it actually needs, not the full surface.

## Listing and listing what's installed

- `ds add --list`: shows the bundled toolpack catalog plus their installed
  status in the current project.
- Custom-added entries appear under `mcp_servers` in `sandstorm.json`;
  inspect the file directly for those.
