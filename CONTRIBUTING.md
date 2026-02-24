# Contributing to Sandstorm

Thanks for your interest in contributing! This guide covers everything you need to get started.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (package manager)
- [E2B](https://e2b.dev) API key (for integration tests)
- [Anthropic](https://console.anthropic.com) API key (for integration tests)

## Dev Setup

```bash
git clone https://github.com/tomascupr/sandstorm.git
cd sandstorm
uv sync --extra dev
```

Copy `.env.example` to `.env` (if available) or create one with your API keys:

```bash
ANTHROPIC_API_KEY=sk-ant-...
E2B_API_KEY=e2b_...
```

### Pre-commit Hooks

We use [pre-commit](https://pre-commit.com) to enforce code quality on every commit:

```bash
uv run pre-commit install
```

This runs ruff lint and format checks automatically before each commit.

## Code Quality

All checks must pass before a PR can be merged:

```bash
ruff check src/ tests/              # Lint
ruff format --check src/ tests/     # Format check
uv run --with pyright pyright src/sandstorm/  # Type check
uv run pytest tests/                # Tests
```

To auto-fix lint and formatting issues:

```bash
ruff check --fix src/ tests/
ruff format src/ tests/
```

## Commit Conventions

We use [Conventional Commits](https://www.conventionalcommits.org):

- `feat:` — new feature
- `fix:` — bug fix
- `docs:` — documentation only
- `refactor:` — code change that neither fixes a bug nor adds a feature
- `test:` — adding or updating tests
- `chore:` — maintenance tasks (CI, deps, config)

Examples:

```
feat: add webhook retry logic
fix: handle empty sandbox response
docs: update OpenRouter configuration guide
```

## Pull Request Process

1. Fork the repo and create a branch from `main`
2. Make your changes — keep PRs focused on a single concern
3. Ensure all checks pass (`ruff check`, `ruff format --check`, `pyright`, `pytest`)
4. Write a clear PR description explaining _what_ and _why_
5. Link related issues with `Fixes #123` or `Closes #123`

## Project Structure

```
src/sandstorm/
├── main.py          # FastAPI app, routes, lifespan
├── sandbox.py       # E2B sandbox lifecycle
├── config.py        # sandstorm.json loading and validation
├── files.py         # File upload/extraction utilities
├── models.py        # Pydantic request models
├── cli.py           # Click CLI (ds command)
├── client.py        # Python client SDK
├── e2b_api.py       # E2B webhook API client
├── slack.py         # Slack bot logic
├── slack_routes.py  # Slack FastAPI router
├── runner.mjs       # Agent runner (runs inside sandbox)
└── auth.py          # API token authentication
```

## Running the Server

```bash
ds serve --reload    # Start dev server with auto-reload
```

## Questions?

Open a [discussion](https://github.com/tomascupr/sandstorm/discussions) or file an [issue](https://github.com/tomascupr/sandstorm/issues).
