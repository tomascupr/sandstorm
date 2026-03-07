# Advanced examples

Start with `ds init` for the default onboarding path. The examples in this directory are more
opinionated patterns you can borrow once you want a tighter workflow than the starter catalog.

## Starter map

| If you want to start with... | Use `ds init` | Then look at these advanced examples |
|------------------------------|---------------|--------------------------------------|
| A flexible general-purpose agent | `general-assistant` | `code-reviewer`, `repo-migration` |
| Research briefs and market scans | `research-brief` | `competitive-analysis`, `content-brief` |
| Document analysis and extraction | `document-analyst` | - |
| Support or issue queue triage | `support-triage` | `issue-triage` |
| API extraction from docs | `api-extractor` | `docs-to-openapi` |
| Security reviews | `security-audit` | `security-auditor` |

## Advanced patterns

| Example | When to use it | Key features |
|---------|----------------|--------------|
| [Competitive Analysis](competitive-analysis/) | Research competitors with a more opinionated market-analysis schema | `output_format`, WebFetch, WebSearch |
| [Content Brief](content-brief/) | Generate a search-driven content brief | `output_format`, WebSearch |
| [Issue Triage](issue-triage/) | Triage uploaded issue exports with a stricter engineering rubric | `output_format`, `allowed_tools`, file uploads |
| [Code Reviewer](code-reviewer/) | Produce a structured code-review report with severity and fixes | `output_format`, `allowed_tools`, file uploads |
| [Repo Migration](repo-migration/) | Plan a staged migration without write access | `output_format`, `allowed_tools`, file uploads |
| [Docs to OpenAPI](docs-to-openapi/) | Crawl docs and generate a draft OpenAPI spec | `output_format`, WebFetch, Write |
| [Security Auditor](security-auditor/) | Run a multi-agent audit with an OWASP skill baked into the project | `agents`, `skills_dir`, `allowed_tools` |

## Typical workflow

```bash
pip install duvo-sandstorm
ds init research-brief

# When you need a narrower pattern, switch to an advanced example
cd examples/competitive-analysis
ds "Compare Vercel, Netlify, and Cloudflare Pages as deployment platforms"
```

## Make your own

1. Start with the closest `ds init` starter.
2. Tighten the prompt, schema, or tool budget for your use case.
3. Add skills or sub-agents only when the workflow really needs them.

See [docs/configuration.md](../docs/configuration.md) for the full config reference.
