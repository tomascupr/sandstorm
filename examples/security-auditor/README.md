# Security Auditor

Multi-agent security audit with OWASP Top 10 skill and structured vulnerability reporting.

## Features Used

- **`agents`** — three specialized sub-agents: dependency scanner, code scanner, and config scanner
- **`skills_dir`** — OWASP Top 10 checklist loaded as a skill for systematic vulnerability detection
- **`output_format`** — structured vulnerability report with severity, CWE IDs, and remediation steps
- **`allowed_tools`** — includes `Task` for spawning sub-agents, plus `Bash` for running audit commands
- **Per-agent model selection** — `config-scanner` uses `haiku` (cheaper for simpler checks)

## Quick Start

```bash
cd examples/security-auditor
ds "Run a security audit on this codebase" -f /path/to/src/auth.py -f /path/to/requirements.txt
```

## More Examples

```bash
# Audit multiple source files
ds "Audit these files for security vulnerabilities" \
  -f src/auth.py -f src/api.py -f src/database.py -f requirements.txt

# Focus on a specific area
ds "Check this code for injection vulnerabilities and hardcoded secrets" -f app/views.py

# Audit configuration
ds "Review these configs for security misconfigurations" \
  -f Dockerfile -f docker-compose.yml -f .github/workflows/deploy.yml

# Full project audit
ds "Perform a comprehensive security audit including dependencies, code, and configuration" \
  -f requirements.txt -f src/main.py -f src/auth.py -f Dockerfile -f .env.example
```

## Sample Output

```json
{
  "risk_level": "high",
  "summary": "Found 5 vulnerabilities across 3 files. One critical SQL injection and two high-severity issues require immediate remediation. Dependencies have 2 known CVEs.",
  "vulnerabilities": [
    {
      "title": "SQL injection via f-string interpolation",
      "severity": "critical",
      "category": "Injection",
      "cwe": "CWE-89",
      "file": "src/auth.py",
      "line": 45,
      "description": "User-supplied email is interpolated directly into a SQL query using an f-string, allowing arbitrary SQL execution.",
      "remediation": "Use parameterized queries: cursor.execute('SELECT * FROM users WHERE email = %s', (email,))"
    },
    {
      "title": "Hardcoded API key in source",
      "severity": "high",
      "category": "Cryptographic Failures",
      "cwe": "CWE-798",
      "file": "src/api.py",
      "line": 12,
      "description": "A Stripe API key is hardcoded as a string literal. This key will be exposed in version control.",
      "remediation": "Move to environment variable: stripe_key = os.environ['STRIPE_API_KEY']"
    },
    {
      "title": "Known CVE in requests 2.28.0",
      "severity": "medium",
      "category": "Vulnerable Components",
      "cwe": "CWE-1104",
      "file": "requirements.txt",
      "line": 3,
      "description": "requests 2.28.0 has CVE-2023-32681 (unintended leak of Proxy-Authorization header).",
      "remediation": "Upgrade to requests >= 2.31.0"
    }
  ],
  "stats": {
    "files_scanned": 4,
    "total_vulnerabilities": 5,
    "critical_count": 1,
    "high_count": 2,
    "medium_count": 1,
    "low_count": 1
  }
}
```

## Architecture

The security auditor uses a multi-agent architecture with three specialized sub-agents:

```
Main Agent (team lead, sonnet)
├── dependency-scanner (sonnet) — pip audit, npm audit, CVE checks
├── code-scanner (sonnet) — OWASP Top 10 static analysis
└── config-scanner (haiku) — configuration review
```

The main agent coordinates the sub-agents via the `Task` tool, collects their findings, deduplicates, and produces the final report.

## Configuration

| Field | Value | Why |
|-------|-------|-----|
| `system_prompt` | Security team lead | Coordinates sub-agents and synthesizes findings |
| `model` | `sonnet` | Strong reasoning for security analysis |
| `skills_dir` | `.claude/skills` | Loads OWASP Top 10 checklist as a skill |
| `allowed_tools` | `["Read", "Glob", "Grep", "Bash", "Task"]` | `Task` enables sub-agent spawning, `Bash` enables `pip audit` etc. `Skill` is auto-added |
| `agents` | 3 sub-agents | Each focuses on a different attack surface |
| `output_format` | JSON schema with vulnerabilities array | Each vulnerability has severity, CWE, file, line, and remediation |

## Customization

- **Add sub-agents** — add a `secret-scanner` agent focused on detecting leaked credentials and API keys
- **Change severity thresholds** — modify the `risk_level` enum to match your organization's risk framework
- **Add compliance mapping** — extend the vulnerability schema with `compliance` fields (SOC 2, HIPAA, PCI DSS)
- **Swap models** — use `opus` for the code scanner for deeper analysis of complex vulnerability patterns
- **Expand the skill** — edit `.claude/skills/owasp-top-10/SKILL.md` to add your organization's custom security policies
