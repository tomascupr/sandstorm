# Security Audit

Starter for deeper security reviews across code, configuration, and dependencies.

## Run it

```bash
ds "Run a security audit on this codebase" -f requirements.txt -f src/auth.py
```

## Example prompts

- Audit this service for the highest-risk security issues and suggest fixes.
- Review these deployment configs for misconfigurations and exposed secrets.
- Check these auth flows for injection, authz, and session handling problems.
- Scan this dependency set plus source files and prioritize the remediation work.

## How to customize

1. Add your compliance context, risk tolerance, or review checklist to `system_prompt_append`.
2. Rewrite the prompt examples so they match the systems your team audits most often.
3. Only replace the base `system_prompt` or sub-agents if you need a different audit model.
