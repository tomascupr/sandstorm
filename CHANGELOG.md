# Changelog

All notable changes to Sandstorm will be documented in this file.

## [Unreleased]

### Documentation

- document runtime provider and local TypeScript client

## [0.9.2] - 2026-04-17

### Bug Fixes

- ci: add package-lock.json so npm publish workflow can run (#50)
- ci: pypi publish skip-existing for release retryability (#51)

No user-facing changes. v0.9.2 exists because v0.9.1's GitHub release
was locked immutable before the publish workflow finished; this tag
re-runs the workflow so `@duvo/sandstorm-client@0.9.2` lands on npm
alongside `duvo-sandstorm==0.9.2` on PyPI. Code content identical to
v0.9.1.

## [0.9.1] - 2026-04-17

### Bug Fixes

- address review findings (C1-C3, H1-H3, M2)

### Documentation

- triggers, MA interop, custom MCPs, memory scopes, Slack updates

### Features

- publish @duvo/sandstorm-client to npm on release
- upgrade streaming to bolt-python 1.28 (loading_messages)
- App Home config UI (read-first, two write actions)
- three-level scope (team / channel / user)
- cancel in-flight runs from Slack, CLI, HTTP
- per-channel default agent overlays
- reaction-triggered runs as a third trigger type
- cron (sub-hourly) + generic webhook primitives
- ds add --custom for arbitrary MCP servers

## [0.9.0] - 2026-04-17

### Bug Fixes

- address /code-reviewer findings (H1–H3, M1, M3, L1, L2)

### Documentation

- README rewrite + comparison/FAQ/multi-llm/memory/replay
- Langfuse/Phoenix/Langsmith setup + local compose

### Features

- TypeScript client @duvo/sandstorm-client
- code-review starter for GitHub PR review agents
- Railway template + Dockerfile polish
- ds upgrade — in-place PyPI upgrade with template-rebuild prompt
- polish ds slack setup + add ds slack verify
- ds doctor preflight checks
- inline tool breadcrumbs for @mention streaming
- pause instead of keep-alive for Slack thread continuity
- resume Agent SDK sessions across thread messages
- ds replay with session fork, budget cap, markdown report
- slash commands /remember /forget /memories /model
- inject user memory into system_prompt at query time
- add user-scoped MemoryStore mirroring RunStore
- extend Run dataclass with replay/resume fields

### Miscellaneous

- upgrade Agent SDK to 0.2.112 and E2B to 2.20

### Refactoring

- fixes from /simplify review

## [0.8.1] - 2026-03-12

### Features

- add Notion, Firecrawl, Exa, and GitHub toolpacks (#46)

### Bug Fixes

- fix Linear toolpack — migrate from removed `@modelcontextprotocol/server-linear` to `linear-mcp`

## [0.8.0] - 2026-03-11

### Features

- add bundled toolpack installation flow (`ds add linear`) (#44)
- add ds init starters and landing-page README (#42)
- improve onboarding and repo polish (#40)
- improve DX and code quality for GitHub growth (#39)
- add API token authentication (#6)
- mount Slack on FastAPI, add file extraction and document tools (#38)

### Bug Fixes

- reject absolute file paths in QueryRequest.files (#41)
- deduplicate config helpers and add mtime guard to dotenv refresh
- preserve dotenv hot reload after startup

## [0.7.1] - 2026-02-20

### Bug Fixes

- use pull_request_target for claude review on fork PRs (#34)

### Documentation

- update API reference for per-request whitelisting (#33)

### Features

- add per-request whitelisting and extra definitions for /query (#27)

### Refactoring

- Slack bot improvements (#35)

## [0.7.0] - 2026-02-19

### Features

- add Slack bot integration (#31)

### Miscellaneous

- release v0.7.0 (#32)

## [0.6.0] - 2026-02-18

### Features

- add /runs endpoint and web dashboard (#28)
- bake document skills (pdf, docx, pptx) into E2B template (#29)
- DX improvements for API docs, config, and error handling (#26)
- batch sandbox writes, metadata, and webhook support (#25)

### Miscellaneous

- release v0.6.0 (#30)

## [0.5.0] - 2026-02-17

### Features

- add optional OpenTelemetry integration (#22)

### Miscellaneous

- release v0.5.0 (#24)

### Other

- Add examples directory with 4 real-world use cases (#23)

## [0.4.5] - 2026-02-15

### Bug Fixes

- resolve version drift, health endpoint disclosure, and add tests
- add Procfile for Nixpacks/Railpack deployments (#16)

### Documentation

- restructure README into scannable core + linked guides (#18)
- add Why Sandstorm section with duvo.ai context (#14)

### Features

- add Claude Code Skills support for E2B sandbox (#20)

### Miscellaneous

- release v0.4.5 (#21)

### Refactoring

- improve maintainability, simplification, and DRY across codebase (#15)

## [0.4.0] - 2026-02-15

### Features

- add --file flag to CLI and update README (#11)
- add pip-installable CLI with default query command (#10)

### Miscellaneous

- update changelog and version for v0.4.0 (#13)
- update changelog and version for v0.3.0 (#9)
- update changelog for v0.2.6

### Other

- Add OpenRouter support

## [0.2.6] - 2026-02-14

### Bug Fixes

- rename package to match pyproject name for Nixpacks deployment

### CI/CD

- add lint, typecheck, and build verification workflow

### Features

- add Google Vertex AI support with GCP service account credentials (#4)

### Other

- Add Claude Code GitHub Workflow (#5)
- Revise README description for clarity and impact

## [0.2.5] - 2026-02-14

### Documentation

- document public E2B template in README

## [0.2.0] - 2026-02-14

### Bug Fixes

- explicitly cancel background task on client disconnect
- make CORS configurable and fix invalid credentials+wildcard
- bound asyncio queue to prevent memory exhaustion
- add missing request_id to task exception log line
- log suppressed task exceptions instead of silent pass
- add error context and directory creation for file uploads
- narrow template fallback to NotFoundException only
- forward stderr from sandbox agent to SSE stream
- remove unused claude-code CLI install from fallback path
- set 30-minute command timeout to prevent hung agents

### Features

- add SSE keepalive ping every 30 seconds
- health check reports API key configuration status
- add file upload limits (max 20 files, 10MB total)
- validate timeout range (5s-3600s)
- validate sandstorm.json structure on load
- add structured logging and request ID tracking

### Miscellaneous

- update changelog for v0.2.0
- pin claude-agent-sdk version for deterministic builds
- add changelog via git-cliff

### Other

- Update README tagline with additional feature highlights (#2)
- Add Deployment section to README (#1)
- Overhaul README for scannability and impact
- Update README with correct repo URL, hosted URLs, and complex agent examples

## [0.1.0] - 2026-02-14

### Features

- initial release of Sandstorm v0.1.0
