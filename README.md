# Sandstorm

Open-source runtime for general-purpose AI agents in isolated sandboxes.

CLI, API, and Slack with streaming, file uploads, and config-driven behavior.

Built on the Claude Agent SDK and E2B.

[![CI](https://github.com/tomascupr/sandstorm/actions/workflows/ci.yml/badge.svg)](https://github.com/tomascupr/sandstorm/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/duvo-sandstorm.svg)](https://pypi.org/project/duvo-sandstorm/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

![Sandstorm live run and dashboard](docs/assets/sandstorm-demo.svg)

Sandstorm is for people who want real agent work, not a chat wrapper:

- Compare competitors and write a brief
- Analyze uploaded transcripts or PDFs
- Triage incoming support tickets
- Crawl docs and draft an API spec
- Run a security audit

## Terminal demo

```bash
$ pip install duvo-sandstorm
$ ds init research-brief
$ cd research-brief
$ ds "Compare Linear, Jira, and Asana for a 50-person product org"

summary: Linear is the best fit for speed and usability, Jira wins on configurability,
and Asana is the easiest cross-functional rollout.
recommendations:
  - Pick Linear for a product-led team that values velocity.
  - Pick Jira if workflow customization is the top priority.
  - Keep Asana for broader non-engineering coordination.
sources:
  - linear.app
  - atlassian.com/software/jira
  - asana.com
```

The point is not just that an agent can answer. It starts from a runnable starter, gets a fresh
sandbox, can read files or use the web, streams its work, and tears itself down when the run is done.

## 60-second path

```bash
pip install duvo-sandstorm
ds init
cd general-assistant
ds "Compare Notion, Coda, and Slite for async product teams"
```

`ds init` scaffolds a runnable starter with `sandstorm.json`, a starter README, `.env.example`,
and any starter-specific assets. If provider settings are missing, the guided flow asks once and
writes `.env` for you.

Direct forms:

```bash
ds init --list
ds init research-brief
ds init security-audit my-audit
```

## Pick a starter

| Starter | Use it when you want to | Typical output | Aliases |
|---------|--------------------------|----------------|---------|
| `general-assistant` | Start with one flexible agent for mixed workflows | concise answer, plan, or artifact | - |
| `research-brief` | Research a topic, compare options, and support a decision | brief with findings, recommendations, and sources | `competitive-analysis` |
| `document-analyst` | Review transcripts, reports, PDFs, or decks | summary, risks, action items, open questions | - |
| `support-triage` | Triage support tickets or issue exports | prioritized queue with owners and next steps | `issue-triage` |
| `api-extractor` | Crawl docs and draft an API summary plus spec | endpoint summary and draft `openapi.yaml` | `docs-to-openapi` |
| `security-audit` | Run a structured security review | vulnerability report with remediation steps | - |

## Why Sandstorm exists

Most agent projects break down in one of two ways:

- You wire the SDK yourself and end up rebuilding sandbox lifecycle, file uploads, streaming,
  config loading, and starter setup.
- You use an agent framework that is good at orchestration but weak at actually shipping a
  runnable agent product path.

Sandstorm is opinionated about the missing middle:

- starter to runnable project in one command
- fresh sandbox per request with teardown by default
- CLI, API, and Slack over the same runtime
- config-driven behavior through `sandstorm.json`
- built-in document tooling for PDF, DOCX, and PPTX workflows

## Why not wire the SDK yourself?

| Capability | Sandstorm | Raw SDK + E2B | DIY runner |
|------------|-----------|---------------|------------|
| Fresh sandbox per request | Built in | Manual wiring | Manual wiring |
| Streaming API endpoint | Built in | Manual wiring | Custom work |
| File uploads | Built in | Manual wiring | Custom work |
| `sandstorm.json` config layer | Built in | No | Custom work |
| Slack bot integration | Built in | No | Custom work |
| Starter scaffolding with `ds init` | Built in | No | Custom work |

## Docs

- [Getting started](docs/getting-started.md)
- [Configuration](docs/configuration.md)
- [API reference](docs/api.md)
- [Slack bot](docs/slack.md)
- [Deployment](docs/deployment.md)
- [OpenRouter](docs/openrouter.md)
- [Advanced examples](examples/README.md)

## Community

If Sandstorm saves you runner plumbing, please [star the repo](https://github.com/tomascupr/sandstorm).

If you want a new starter, a provider integration, or a sharper deploy story, open an issue or
start a discussion.
