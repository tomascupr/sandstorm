# Examples

Ready-to-use `sandstorm.json` configs for common use cases. Each example is a self-contained directory — `cd` into it and run a prompt.

## Quick Start

```bash
pip install duvo-sandstorm
export ANTHROPIC_API_KEY=sk-ant-...
export E2B_API_KEY=e2b_...

cd examples/code-reviewer
ds "Review this code for bugs" -f /path/to/your/file.py
```

## Examples

| Example | What it does | Difficulty |
|---------|-------------|------------|
| [Code Reviewer](code-reviewer/) | Structured code review with severity ratings | Beginner |
| [Competitive Analysis](competitive-analysis/) | Research and compare competitors | Intermediate |
| [Content Brief](content-brief/) | Generate content briefs with SEO research | Intermediate |
| [Security Auditor](security-auditor/) | Multi-agent security audit with OWASP skill | Advanced |

## Feature Matrix

| Feature | Code Reviewer | Competitive Analysis | Content Brief | Security Auditor |
|---------|:---:|:---:|:---:|:---:|
| `system_prompt` | x | x | x | x |
| `output_format` | x | x | x | x |
| `allowed_tools` | x | | | x |
| `agents` | | | | x |
| `skills_dir` | | | | x |
| `max_turns` | | x | x | |
| File uploads (`-f`) | x | | | x |
| WebFetch | | x | | |
| WebSearch | | x | x | |
| Read-only sandbox | x | | | |
| Multi-agent | | | | x |

## How Examples Work

Each example directory contains:

- **`sandstorm.json`** — the agent configuration (system prompt, output format, tools, etc.)
- **`README.md`** — usage guide with example prompts and sample output

When you run `ds` from an example directory, Sandstorm loads the local `sandstorm.json` automatically. No code changes needed — just `cd` and run.

## Creating Your Own

1. Create a new directory with a `sandstorm.json`
2. Start with one of the examples above as a template
3. Customize the `system_prompt`, `output_format`, and other fields
4. Run `ds "your prompt"` to test

See the [Configuration](../README.md#configuration) section in the main README for all available fields.
