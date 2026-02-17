# OSS Evals for Sandstorm — Implementation Plan

## Use Case

Sandstorm users define agent configs (`sandstorm.json`) with system prompts, tools, and structured output schemas. Today there's no way to systematically verify that a config produces correct results. Users tweak prompts blind, with no feedback loop.

**Who needs this:**
1. **Config authors** — "Does my code-reviewer config actually catch SQL injection?"
2. **Sandstorm developers** — "Did upgrading the SDK version regress output quality?"
3. **OSS contributors** — "My PR improves prompt X — here's the eval to prove it."

**What "easy" means:**
- Declarative YAML files — no Python/JS scoring code to write
- Built into the CLI — `ds eval` just works
- Reuses existing `sandstorm.json` configs — no parallel config system
- Fast feedback — parallel execution, clear pass/fail output

## Eval File Format

Evals live as YAML files (e.g. `evals/code-reviewer.eval.yaml`) alongside your project:

```yaml
name: Code Reviewer Evals
# Optional: path to sandstorm.json (defaults to ./sandstorm.json)
config: sandstorm.json

cases:
  - name: detects-sql-injection
    prompt: "Review this code for security issues"
    files:
      app.py: |
        def get_user(id):
            query = f"SELECT * FROM users WHERE id = {id}"
            return db.execute(query)
    assertions:
      - type: json_path
        path: "$.findings[*].category"
        contains: "security"

  - name: clean-code-no-criticals
    prompt: "Review this code"
    files:
      hello.py: |
        def greet(name: str) -> str:
            return f"Hello, {name}!"
    assertions:
      - type: json_path
        path: "$.stats.critical_count"
        equals: 0

  - name: explains-well
    prompt: "Explain this function"
    files:
      math.py: |
        def fib(n):
            if n <= 1: return n
            return fib(n-1) + fib(n-2)
    assertions:
      - type: contains
        value: "recursive"
      - type: llm_judge
        criteria: "Does the response correctly explain that this is a Fibonacci function with exponential time complexity?"
```

## Assertion Types

| Type | Fields | Description |
|------|--------|-------------|
| `equals` | `value` | Exact match on full output (string) |
| `contains` | `value` | Substring present in output |
| `regex` | `pattern` | Regex matches against output |
| `json_path` | `path`, + `equals`/`contains`/`regex` | Extract value from structured JSON output, then check |
| `llm_judge` | `criteria` | Claude grades the output against freeform criteria (pass/fail) |

## Architecture

### New Files

1. **`src/sandstorm/eval_models.py`** — Pydantic models for eval YAML
   - `EvalAssertion` (type, value, path, pattern, criteria)
   - `EvalCase` (name, prompt, files, assertions, timeout)
   - `EvalSuite` (name, config, cases)
   - `EvalCaseResult` (case name, passed, assertion results, cost, duration)
   - `EvalReport` (suite name, results, summary stats)

2. **`src/sandstorm/eval_runner.py`** — Core eval execution
   - `run_eval_suite()` — iterates cases, calls `run_agent_in_sandbox`, scores output
   - `check_assertion()` — dispatches to assertion checkers
   - `_check_equals()`, `_check_contains()`, `_check_regex()`, `_check_json_path()`, `_check_llm_judge()`
   - Extracts structured output from the result event stream

3. **`src/sandstorm/cli.py`** — Add `ds eval` command
   - `ds eval [PATH]` — run eval file(s), default `evals/` directory
   - `--concurrency N` — parallel sandbox execution (default 3)
   - `--json-output` — machine-readable results
   - `--filter PATTERN` — run only matching case names
   - Pretty terminal output with pass/fail indicators

4. **`tests/test_eval_models.py`** — Unit tests for eval model validation
5. **`tests/test_eval_runner.py`** — Unit tests for assertion checking (mocked sandbox)

### Modified Files

- **`pyproject.toml`** — add `pyyaml` dependency, `jsonpath-ng` dependency
- **`src/sandstorm/cli.py`** — add `eval` command to CLI group

## CLI Output

```
$ ds eval evals/code-reviewer.eval.yaml

Code Reviewer Evals
  ✓ detects-sql-injection (3 assertions passed) [$0.0123, 12s]
  ✗ clean-code-no-criticals [$0.0089, 8s]
    ✗ json_path $.stats.critical_count equals 0 — got 1
    ✓ json_path $.stats.warning_count >= 0
  ✓ explains-well (2 assertions passed) [$0.0045, 6s]

Results: 2/3 passed | Total cost: $0.0257 | Duration: 26s
```

## Implementation Steps

1. Add `pyyaml` and `jsonpath-ng` to dependencies in `pyproject.toml`
2. Create `src/sandstorm/eval_models.py` with Pydantic models
3. Create `src/sandstorm/eval_runner.py` with assertion checking and suite execution
4. Add `ds eval` command to `src/sandstorm/cli.py`
5. Create `tests/test_eval_models.py` with validation tests
6. Create `tests/test_eval_runner.py` with assertion checker tests
7. Add an example eval file in `examples/code-reviewer/evals/`
