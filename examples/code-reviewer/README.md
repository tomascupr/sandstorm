# Code Reviewer

Structured code review with severity ratings and actionable fix suggestions.

## Features Used

- **`output_format`** — returns findings as validated JSON with severity, category, file, line, and suggestion
- **`allowed_tools`** — restricted to read-only tools (`Read`, `Glob`, `Grep`) so the agent can't modify your code
- **`system_prompt`** — expert reviewer persona focused on bugs, security, and maintainability

## Quick Start

```bash
cd examples/code-reviewer
ds "Review this code for bugs and security issues" -f /path/to/your/file.py
```

## More Examples

```bash
# Review multiple files
ds "Review these files for security vulnerabilities" -f src/auth.py -f src/api.py

# Focus on performance
ds "Analyze this code for performance bottlenecks and N+1 queries" -f app/models.py -f app/views.py

# Review a specific concern
ds "Check this code for proper error handling and edge cases" -f lib/parser.py

# Review with context
ds "Review this database migration for data loss risks" -f migrations/0042_alter_user.py
```

## Sample Output

```json
{
  "summary": "Found 3 issues across 2 files. One critical SQL injection vulnerability in the auth module requires immediate attention.",
  "findings": [
    {
      "severity": "critical",
      "category": "security",
      "file": "src/auth.py",
      "line": 45,
      "title": "SQL injection via string formatting",
      "description": "User input is interpolated directly into a SQL query using f-string formatting, allowing an attacker to execute arbitrary SQL.",
      "suggestion": "Use parameterized queries: cursor.execute('SELECT * FROM users WHERE email = %s', (email,))"
    },
    {
      "severity": "warning",
      "category": "bug",
      "file": "src/auth.py",
      "line": 72,
      "title": "Unchecked None return value",
      "description": "get_user() can return None when the user is not found, but the return value is accessed without a null check on line 73.",
      "suggestion": "Add a guard clause: if user is None: raise UserNotFoundError(user_id)"
    },
    {
      "severity": "info",
      "category": "maintainability",
      "file": "src/utils.py",
      "line": 12,
      "title": "Broad exception catch",
      "description": "Catching bare Exception hides bugs and makes debugging harder.",
      "suggestion": "Catch specific exceptions: except (ValueError, KeyError) as e:"
    }
  ],
  "stats": {
    "files_reviewed": 2,
    "total_findings": 3,
    "critical_count": 1,
    "warning_count": 1
  }
}
```

## Configuration

| Field | Value | Why |
|-------|-------|-----|
| `system_prompt` | Expert code reviewer persona | Focuses the agent on bugs, security, and maintainability — not style |
| `model` | `sonnet` | Good balance of speed and quality for code analysis |
| `allowed_tools` | `["Read", "Glob", "Grep"]` | Read-only access — the agent can analyze but never modify your code |
| `output_format` | JSON schema with findings array | Each finding has severity, category, file, line, title, description, and suggestion |

## Customization

- **Add severity levels** — extend the `severity` enum with `"high"` and `"low"` for finer granularity
- **Add categories** — add `"accessibility"`, `"testing"`, or `"documentation"` to the `category` enum
- **Change model** — use `"opus"` for deeper analysis of complex codebases, `"haiku"` for quick checks
- **Allow writes** — add `"Write"` to `allowed_tools` if you want the agent to also fix the issues it finds
