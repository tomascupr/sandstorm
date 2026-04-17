# Code Review

Starter for an agent that reviews pull requests, pulls the diff from GitHub,
checks out the repo, runs the tests, and posts a review with inline comments.

## Run it

From the repo root:

```bash
ds "Review PR 123 in owner/repo, focus on security and API breakage"
```

In Slack (after `ds slack start`):

```
@Sandstorm review PR https://github.com/owner/repo/pull/123
```

## Environment

Create `.env` from `.env.example` and populate:

- `ANTHROPIC_API_KEY`
- `E2B_API_KEY`
- `GITHUB_PERSONAL_ACCESS_TOKEN`: a fine-grained PAT with `Contents: read`,
  `Pull requests: read/write`, and `Metadata: read` on the target repo(s)
- `LINEAR_API_KEY`: optional, lets the agent cross-reference tickets when
  the PR title or body mentions one

## Example prompts

- Review PR 123 in owner/repo and leave inline comments on material issues.
- Compare this PR against the description, call out anything out-of-scope.
- What's blocking this PR from shipping? Read the CI logs and diff first.
- Triage the last five PRs in owner/repo by risk and suggest review order.

## Tuning

1. Add team conventions, required checks, or banned patterns to
   `system_prompt_append` in `sandstorm.json`.
2. Narrow `allowed_tools` if the agent should not be allowed to run tests
   locally, e.g. drop `Bash` to make it a pure read-only reviewer.
3. Switch `model` to `"opus"` for dense, complex reviews and `"haiku"` for
   high-volume triage of small PRs.
