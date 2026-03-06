# Repo Migration

Plan a staged migration for an existing codebase or service without giving the agent write access.

## Features Used

- **`output_format`** -- returns a migration plan with phases, blockers, validation checks, and
  likely file touchpoints
- **`allowed_tools`** -- restricted to `Read`, `Glob`, and `Grep` so the example stays analysis-only
- **File uploads** -- send representative files from the current stack to ground the plan

## Quick Start

```bash
cd examples/repo-migration
ds "Plan a staged migration from Flask + Celery to FastAPI + Temporal" \
  -f /path/to/app.py \
  -f /path/to/requirements.txt \
  -f /path/to/worker.py
```

## More Examples

```bash
# Monolith to services
ds "Plan a migration from this Rails monolith to service boundaries with minimal downtime" \
  -f app/controllers/orders_controller.rb \
  -f app/models/order.rb

# Infrastructure change
ds "Plan a migration from Docker Compose to Kubernetes for this service" \
  -f Dockerfile \
  -f docker-compose.yml

# Library/runtime upgrade
ds "Plan a migration from Pydantic v1 to v2 across this codebase" \
  -f src/models.py \
  -f requirements.txt
```

## Sample Output

```json
{
  "summary": "The migration is feasible in 4 phases. The main risks are background job semantics and auth/session coupling.",
  "current_stack": "Flask API with Celery workers, Redis broker, and SQLAlchemy models",
  "target_state": "FastAPI service with Temporal workflows and async request handling",
  "phases": [
    {
      "name": "Stabilize boundaries",
      "goal": "Separate HTTP, domain, and worker concerns before framework changes",
      "tasks": [
        "Extract request validation into dedicated schema modules",
        "Move Celery task orchestration behind a domain service layer"
      ],
      "risks": ["Hidden imports from Flask globals"],
      "success_criteria": ["Endpoints can call domain logic without Flask-specific objects"]
    }
  ],
  "files_to_touch": ["app.py", "worker.py", "requirements.txt"],
  "blockers": ["No integration tests around worker retries"],
  "validation_plan": ["Add smoke tests for core endpoints before the migration starts"]
}
```
