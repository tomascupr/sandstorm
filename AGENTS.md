# Repository Guidelines

## Project Structure & Module Organization
Core application code lives in `src/sandstorm/`. Key modules include `main.py` for the FastAPI app, `cli.py` for the `ds` CLI, `sandbox.py` for E2B orchestration, and `slack.py` / `slack_routes.py` for Slack support. Deployment entrypoints live in `api/`, documentation in `docs/`, runnable configs in `examples/`, and test coverage in `tests/`. Keep new modules inside `src/sandstorm/` and mirror them with focused tests such as `tests/test_auth.py`.

## Build, Test, and Development Commands
Use Python 3.11+ and `uv`.

```bash
uv sync --extra dev              # install app + dev dependencies
ds serve --reload                # run the FastAPI server locally
uv run pytest tests/             # run the test suite
ruff check src/ tests/           # lint
ruff format --check src/ tests/  # formatting check
uv run pyright src/sandstorm/  # type check
uv run python -c "from sandstorm.main import app"  # smoke-test imports
```

If you use hooks locally, install them with `uv run pre-commit install`.

## Coding Style & Naming Conventions
Follow Ruff defaults with the repo’s configured 99-character line length. Use 4-space indentation, snake_case for modules, functions, and variables, and PascalCase for classes. Keep FastAPI request/response models in `models.py`-style modules and prefer small, composable helpers over large route handlers. Run `ruff check --fix src/ tests/` and `ruff format src/ tests/` before opening a PR.

## Testing Guidelines
Tests use `pytest` and live under `tests/` with filenames matching `test_<feature>.py`. Prefer fixtures in `tests/conftest.py` and mock E2B or external API calls instead of hitting live services in unit tests. Some optional-path tests skip when Slack or OpenTelemetry extras are absent; install the relevant extras when working in those areas. For manual end-to-end work, use `.env.example` as the template and never commit real API keys.

## Commit & Pull Request Guidelines
Recent history follows Conventional Commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`. Keep commits scoped to one change. PRs should explain what changed, why it changed, and link the related issue (`Fixes #123`). Include screenshots or sample CLI/API output when changing user-facing behavior such as Slack flows, dashboard HTML, or streamed responses.
