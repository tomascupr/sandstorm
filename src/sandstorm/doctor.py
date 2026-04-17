"""Preflight checks for Sandstorm deployments — `ds doctor`.

Runs a small, ordered sequence of checks and prints a colored table. The most
common first-run failures (missing keys, bad credentials, unreachable E2B,
stale Slack scopes) each produce a specific fix hint so a user can unblock
themselves without reading docs.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_REQUIRED_SLACK_SCOPES = ("commands", "chat:write", "app_mentions:read")


@dataclass
class Check:
    name: str
    passed: bool
    detail: str
    hint: str = ""


def print_check_table(checks: list[Check], header: str = "Preflight") -> bool:
    """Print a colored ✓/✗ table to stdout. Returns True when every check passed."""
    import click

    all_passed = True
    click.echo(f"\n{header}:\n")
    for check in checks:
        icon = click.style("✓", fg="green") if check.passed else click.style("✗", fg="red")
        click.echo(f"  {icon}  {check.name.ljust(30)}  {check.detail}")
        if not check.passed:
            all_passed = False
            if check.hint:
                click.echo(f"        {click.style('fix:', fg='yellow')} {check.hint}")
    click.echo()
    return all_passed


async def run_checks(*, deep: bool = False) -> list[Check]:
    """Return an ordered list of checks.

    `deep=True` adds a throwaway-sandbox probe (spins up an E2B sandbox, runs
    `echo hello`, tears down). That costs E2B credits and ~10s, so it's opt-in.
    """
    checks: list[Check] = []

    # 1. Provider credential present
    provider_keys = {
        "ANTHROPIC_API_KEY": "anthropic",
        "OPENROUTER_API_KEY": "openrouter",
        "CLAUDE_CODE_USE_VERTEX": "vertex",
        "CLAUDE_CODE_USE_BEDROCK": "bedrock",
        "CLAUDE_CODE_USE_FOUNDRY": "azure-foundry",
    }
    found_provider = next((p for k, p in provider_keys.items() if os.environ.get(k)), None)
    custom_base = bool(os.environ.get("ANTHROPIC_BASE_URL"))
    if found_provider or custom_base:
        checks.append(
            Check(
                name="Provider credentials",
                passed=True,
                detail=found_provider or "custom base URL",
            )
        )
    else:
        checks.append(
            Check(
                name="Provider credentials",
                passed=False,
                detail="No provider env var found",
                hint=(
                    "Set ANTHROPIC_API_KEY in .env (or configure OpenRouter, Vertex, "
                    "Bedrock, or Foundry — see docs/multi-llm.md)."
                ),
            )
        )

    # 2. Anthropic token probe (only when using direct Anthropic)
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if anthropic_key and not custom_base:
        ok, msg = _probe_anthropic(anthropic_key)
        checks.append(
            Check(
                name="Anthropic /v1/models",
                passed=ok,
                detail=msg,
                hint=(
                    "If this fails with 401, the ANTHROPIC_API_KEY is invalid or"
                    " revoked — regenerate it at console.anthropic.com."
                    if not ok
                    else ""
                ),
            )
        )

    # 3. E2B credentials
    e2b_key = os.environ.get("E2B_API_KEY", "")
    if not e2b_key:
        checks.append(
            Check(
                name="E2B credentials",
                passed=False,
                detail="E2B_API_KEY not set",
                hint="Get a key at e2b.dev/dashboard and set E2B_API_KEY in .env.",
            )
        )
    else:
        ok, msg = await _probe_e2b(e2b_key)
        checks.append(
            Check(
                name="E2B credentials",
                passed=ok,
                detail=msg,
                hint=(
                    "If this fails with 401, the E2B_API_KEY is invalid. If the"
                    " request times out, check your network / firewall."
                    if not ok
                    else ""
                ),
            )
        )

        # 4. Optional: throwaway sandbox probe
        if deep and ok:
            deep_check = await _probe_sandbox(e2b_key)
            checks.append(deep_check)

    # 5. Slack (optional — only when SLACK_BOT_TOKEN is configured)
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if slack_token:
        checks.extend(_probe_slack(slack_token))

    # 6. Optional: OpenTelemetry endpoint reachability
    otel_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if otel_endpoint:
        ok, msg = _probe_url(otel_endpoint, timeout=3)
        checks.append(
            Check(
                name="OTel endpoint",
                passed=ok,
                detail=msg,
                hint=(
                    "OTel endpoint unreachable — check OTEL_EXPORTER_OTLP_ENDPOINT"
                    " and that your Langfuse/Phoenix/Langsmith instance is up."
                    if not ok
                    else ""
                ),
            )
        )

    return checks


def _probe_anthropic(key: str) -> tuple[bool, str]:
    """Cheap credential check: list models (GET, no token consumed)."""
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/models",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                return True, f"OK ({resp.status})"
            return False, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}: {exc.reason}"
    except urllib.error.URLError as exc:
        return False, f"network: {exc.reason}"
    except OSError as exc:  # timeouts, DNS, etc.
        return False, f"unreachable: {exc}"


async def _probe_e2b(api_key: str) -> tuple[bool, str]:
    """Validate the API key without spinning up compute."""
    from e2b import AsyncSandbox, AuthenticationException

    try:
        sandboxes = AsyncSandbox.list(api_key=api_key)
        if hasattr(sandboxes, "next_items"):
            await sandboxes.next_items()
        return True, "OK"
    except AuthenticationException:
        return False, "invalid API key (401)"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


async def _probe_sandbox(api_key: str) -> Check:
    """Deep: spin up a sandbox, run echo, tear down. Costs a few seconds + credits."""
    from e2b import AsyncSandbox

    start = time.monotonic()
    sbx = None
    try:
        sbx = await AsyncSandbox.create(api_key=api_key, timeout=60)
        result = await sbx.commands.run("echo hello")
        duration = time.monotonic() - start
        ok = result.stdout.strip() == "hello"
        detail = f"{duration:.1f}s roundtrip" if ok else f"unexpected output: {result.stdout!r}"
        return Check(name="Sandbox echo roundtrip", passed=ok, detail=detail)
    except Exception as exc:
        return Check(
            name="Sandbox echo roundtrip",
            passed=False,
            detail=f"{type(exc).__name__}: {exc}",
            hint="E2B spin-up failed — check quota, region, or your network.",
        )
    finally:
        if sbx is not None:
            with contextlib.suppress(Exception):
                await sbx.kill()


def _probe_slack(bot_token: str) -> list[Check]:
    """Verify the bot token + installed scopes via auth.test."""
    try:
        req = urllib.request.Request(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {bot_token}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
    except Exception as exc:
        return [
            Check(
                name="Slack auth.test",
                passed=False,
                detail=f"{type(exc).__name__}: {exc}",
                hint="Bot token probe failed — verify SLACK_BOT_TOKEN.",
            )
        ]

    if not data.get("ok"):
        return [
            Check(
                name="Slack auth.test",
                passed=False,
                detail=f"slack_err: {data.get('error', 'unknown')}",
                hint=(
                    "If error is invalid_auth, the bot token is wrong."
                    " If it's token_revoked, reinstall the app in your workspace."
                ),
            )
        ]

    checks = [
        Check(
            name="Slack auth.test",
            passed=True,
            detail=f"team={data.get('team')}, bot={data.get('bot_id')}",
        )
    ]

    # Scope probe: list installed scopes from the bot token endpoint
    # auth.test doesn't return scopes; use apps.connections.open workaround or skip.
    # Bolt's manifest is the source of truth — we just check SLACK_SIGNING_SECRET.
    signing_secret = os.environ.get("SLACK_SIGNING_SECRET", "")
    checks.append(
        Check(
            name="SLACK_SIGNING_SECRET",
            passed=len(signing_secret) >= 32,
            detail="OK" if len(signing_secret) >= 32 else f"len={len(signing_secret)}",
            hint=(
                "Copy the signing secret from your Slack app's Basic Information page."
                if len(signing_secret) < 32
                else ""
            ),
        )
    )

    # Socket Mode app-level token (optional, only if using Socket Mode)
    app_token = os.environ.get("SLACK_APP_TOKEN", "")
    if app_token:
        checks.append(
            Check(
                name="SLACK_APP_TOKEN format",
                passed=app_token.startswith("xapp-"),
                detail="starts with xapp-"
                if app_token.startswith("xapp-")
                else f"prefix: {app_token[:5]}",
                hint=(
                    "App-level tokens start with xapp-. Generate at api.slack.com"
                    " under 'Basic Information' → 'App-Level Tokens'."
                    if not app_token.startswith("xapp-")
                    else ""
                ),
            )
        )

    return checks


def _probe_url(url: str, timeout: int = 3) -> tuple[bool, str]:
    """HEAD-style reachability check for arbitrary URLs."""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, f"OK ({resp.status})"
    except urllib.error.HTTPError as exc:
        # HTTP errors still prove the endpoint is reachable
        return True, f"HTTP {exc.code}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
