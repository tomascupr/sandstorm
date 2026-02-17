# OWASP Top 10 Security Audit Checklist

Use this checklist when performing security audits. Check each category systematically against the codebase.

## A01:2021 — Broken Access Control

- [ ] Missing authorization checks on endpoints
- [ ] Insecure direct object references (IDOR)
- [ ] Missing function-level access control
- [ ] CORS misconfiguration allowing unauthorized origins
- [ ] Path traversal via user-controlled file paths
- [ ] JWT token manipulation or missing validation

## A02:2021 — Cryptographic Failures

- [ ] Hardcoded secrets, API keys, or passwords in source
- [ ] Weak hashing algorithms (MD5, SHA1 for passwords)
- [ ] Missing encryption for sensitive data at rest
- [ ] HTTP used instead of HTTPS for sensitive endpoints
- [ ] Weak or missing TLS configuration
- [ ] Predictable random values for security tokens

## A03:2021 — Injection

- [ ] SQL injection via string concatenation or f-strings
- [ ] Command injection via `os.system()`, `subprocess.shell=True`
- [ ] XSS via unescaped user input in HTML templates
- [ ] LDAP injection in directory queries
- [ ] NoSQL injection in MongoDB/DynamoDB queries
- [ ] Template injection (Jinja2, Mako, etc.)

## A04:2021 — Insecure Design

- [ ] Missing rate limiting on authentication endpoints
- [ ] No account lockout after failed login attempts
- [ ] Missing CSRF protection on state-changing operations
- [ ] Lack of input validation at trust boundaries
- [ ] Missing re-authentication for sensitive operations

## A05:2021 — Security Misconfiguration

- [ ] Debug mode enabled in production
- [ ] Default credentials still active
- [ ] Unnecessary features or services enabled
- [ ] Missing security headers (CSP, X-Frame-Options, etc.)
- [ ] Verbose error messages exposing stack traces
- [ ] Overly permissive file/directory permissions

## A06:2021 — Vulnerable and Outdated Components

- [ ] Dependencies with known CVEs
- [ ] Outdated frameworks or libraries
- [ ] Unmaintained or abandoned packages
- [ ] Missing lock files (package-lock.json, poetry.lock)
- [ ] Using deprecated APIs or functions

## A07:2021 — Identification and Authentication Failures

- [ ] Weak password policies
- [ ] Missing multi-factor authentication for admin
- [ ] Session tokens in URLs
- [ ] Session not invalidated on logout
- [ ] Missing brute-force protection

## A08:2021 — Software and Data Integrity Failures

- [ ] Missing integrity checks on CI/CD pipeline
- [ ] Insecure deserialization (pickle, yaml.load, eval)
- [ ] Missing signature verification on updates
- [ ] Untrusted data used in serialization

## A09:2021 — Security Logging and Monitoring Failures

- [ ] Missing logging for authentication events
- [ ] Sensitive data logged (passwords, tokens, PII)
- [ ] No alerting for suspicious activity
- [ ] Logs stored without tamper protection

## A10:2021 — Server-Side Request Forgery (SSRF)

- [ ] User-controlled URLs fetched server-side without validation
- [ ] Missing allowlist for external service calls
- [ ] Internal metadata endpoints accessible (cloud provider metadata)
- [ ] DNS rebinding vulnerabilities
