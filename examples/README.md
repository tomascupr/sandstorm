# Examples

Ready-to-use `sandstorm.json` configs for common use cases. Each example is a self-contained
directory: `cd` into it, run `ds "<prompt>"`, and adjust the prompt or schema to fit your
workflow.

## Fastest Starters

```bash
pip install duvo-sandstorm
export ANTHROPIC_API_KEY=sk-ant-...
export E2B_API_KEY=e2b_...

cd examples/competitive-analysis
ds "Compare Notion, Coda, and Slite for async product teams"
```

If you only try three examples first, use these:

- [Competitive Analysis](competitive-analysis/) for live web research
- [Content Brief](content-brief/) for search-driven content planning
- [Issue Triage](issue-triage/) for uploaded reports, tickets, and transcripts

## Pick A Starting Point

| Example | Best when you want to | Key features |
|---------|------------------------|--------------|
| [Competitive Analysis](competitive-analysis/) | Compare competitors using live web research | `output_format`, WebFetch, WebSearch |
| [Content Brief](content-brief/) | Build an SEO/content brief from search results | `output_format`, WebSearch |
| [Issue Triage](issue-triage/) | Classify and prioritize uploaded reports, tickets, or transcripts | `output_format`, `allowed_tools`, file uploads |
| [Code Reviewer](code-reviewer/) | Review uploaded code with a strict JSON report | `output_format`, `allowed_tools`, file uploads |
| [Repo Migration](repo-migration/) | Plan a staged migration for a repo or service | `output_format`, `allowed_tools`, file uploads |
| [Docs to OpenAPI](docs-to-openapi/) | Crawl docs and extract endpoints into a draft spec | `output_format`, WebFetch, Write |
| [Security Auditor](security-auditor/) | Run a multi-agent security audit with skills | `agents`, `skills_dir`, `allowed_tools` |

## How Examples Work

Each example directory contains:

- **`sandstorm.json`** — the agent configuration (system prompt, output format, tools, etc.)
- **`README.md`** — usage guide with example prompts and sample output

When you run `ds` from an example directory, Sandstorm loads the local `sandstorm.json` automatically. No code changes needed — just `cd` and run.

## Typical Commands

```bash
# Research competitors
cd examples/competitive-analysis
ds "Compare Notion, Coda, and Slite for async product teams"

# Build a content brief
cd examples/content-brief
ds "Create a content brief for a blog post about AI support automation"

# Triage uploaded issues
cd examples/issue-triage
ds "Triage these support tickets for severity and next action" -f /path/to/issues.json
```

## Creating Your Own

1. Create a new directory with a `sandstorm.json`
2. Start with one of the examples above as a template
3. Customize the `system_prompt`, `output_format`, and other fields
4. Run `ds "your prompt"` to test

See the [Configuration](../README.md#configuration) section in the main README for all available fields.
