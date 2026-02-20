# Changelog

All notable changes to Sandstorm will be documented in this file.

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


