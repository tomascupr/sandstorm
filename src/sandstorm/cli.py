"""CLI interface for Sandstorm — run the server or execute one-off queries."""

import asyncio
import json
import logging
import os
import secrets
import sys
import urllib.error
import urllib.request
from pathlib import Path

import click
from dotenv import load_dotenv

from sandstorm import _LOG_DATEFMT, _LOG_FORMAT, __version__

_E2B_WEBHOOK_API = "https://api.e2b.app/events/webhooks"


class _DefaultQueryGroup(click.Group):
    """Click group that treats unknown first arguments as query prompts."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        if args and args[0] not in self.commands and not args[0].startswith("-"):
            args.insert(0, "query")
        return super().parse_args(ctx, args)


def _print_event(line: str) -> None:
    """Parse a JSON event line and print it to the appropriate stream."""
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        click.echo(line, nl=False)
        return

    event_type = event.get("type")

    if event_type == "assistant":
        message = event.get("message", {})
        for block in message.get("content", []):
            if block.get("type") == "text":
                click.echo(block["text"], nl=False)
            elif block.get("type") == "tool_use":
                click.echo(f"[tool: {block.get('name', 'unknown')}]", nl=False, err=True)

    elif event_type == "result":
        subtype = event.get("subtype", "unknown")
        num_turns = event.get("num_turns", "?")
        cost = event.get("cost_usd")
        cost_str = f"${cost:.4f}" if cost is not None else "n/a"
        click.echo(
            f"\n--- Result: {subtype} | turns: {num_turns} | cost: {cost_str} ---",
            err=True,
        )
        structured_output = event.get("structured_output")
        if structured_output is not None:
            click.echo(json.dumps(structured_output, indent=2))

    elif event_type == "error":
        click.echo(f"Error: {event.get('error', 'unknown')}", err=True)


@click.group(cls=_DefaultQueryGroup)
@click.version_option(version=__version__, prog_name="sandstorm")
def cli() -> None:
    """Sandstorm — Run Claude agents in E2B sandboxes."""


@cli.command()
@click.option("--host", default="0.0.0.0", help="Bind address.")
@click.option("--port", "-p", default=8000, type=int, help="Bind port.")
@click.option("--reload", is_flag=True, help="Enable auto-reload for development.")
def serve(host: str, port: int, reload: bool) -> None:
    """Start the Sandstorm API server."""
    load_dotenv()

    import uvicorn

    uvicorn.run("sandstorm.main:app", host=host, port=port, reload=reload)


@cli.command()
@click.argument("prompt")
@click.option("--model", "-m", default=None, help="Model to use.")
@click.option("--max-turns", default=None, type=int, help="Maximum agent turns.")
@click.option("--timeout", "-t", default=300, type=int, help="Sandbox timeout (s).")
@click.option("--json-output", is_flag=True, help="Output raw JSON lines.")
@click.option(
    "--anthropic-api-key",
    default=None,
    help="Anthropic API key [env: ANTHROPIC_API_KEY].",
)
@click.option(
    "--e2b-api-key",
    default=None,
    help="E2B API key [env: E2B_API_KEY].",
)
@click.option(
    "--openrouter-api-key",
    default=None,
    help="OpenRouter API key [env: OPENROUTER_API_KEY].",
)
@click.option(
    "--file",
    "-f",
    "file_paths",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, resolve_path=True),
    help="File to upload to the sandbox (repeatable).",
)
def query(
    prompt: str,
    model: str | None,
    max_turns: int | None,
    timeout: int,
    json_output: bool,
    anthropic_api_key: str | None,
    e2b_api_key: str | None,
    openrouter_api_key: str | None,
    file_paths: tuple[str, ...],
) -> None:
    """Run a one-off agent query in a sandbox."""
    load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format=_LOG_FORMAT,
        datefmt=_LOG_DATEFMT,
        stream=sys.stderr,
    )

    from .models import QueryRequest
    from .sandbox import run_agent_in_sandbox

    files: dict[str, str] | None = None
    if file_paths:
        files = {}
        cwd = Path.cwd()
        for fp in file_paths:
            p = Path(fp)
            try:
                rel_path = p.relative_to(cwd)
            except ValueError:
                # File is outside CWD — use basename only
                rel_path = Path(p.name)
            key = str(rel_path)
            try:
                files[key] = p.read_text()
            except UnicodeDecodeError as exc:
                click.echo(f"Error: {key} is not a text file", err=True)
                raise SystemExit(1) from exc

    try:
        request = QueryRequest(
            prompt=prompt,
            model=model,
            max_turns=max_turns,
            timeout=timeout,
            files=files,
            anthropic_api_key=anthropic_api_key,
            e2b_api_key=e2b_api_key,
            openrouter_api_key=openrouter_api_key,
        )
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    async def _run() -> None:
        async for line in run_agent_in_sandbox(request, "cli"):
            if json_output:
                click.echo(line)
            else:
                _print_event(line)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt as exc:
        click.echo("Interrupted.", err=True)
        raise SystemExit(130) from exc


# ── Webhook management ─────────────────────────────────────────────────────


def _get_e2b_api_key(explicit: str | None) -> str:
    """Resolve E2B API key from flag, env, or .env file."""
    key = explicit or os.environ.get("E2B_API_KEY", "")
    if not key:
        click.echo("Error: E2B API key required (--e2b-api-key or E2B_API_KEY)", err=True)
        raise SystemExit(1)
    return key


def _webhook_request(
    method: str, path: str, api_key: str, data: dict | None = None
) -> dict | list | None:
    """Make a request to the E2B webhook API."""
    url = f"{_E2B_WEBHOOK_API}{path}"
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        click.echo(f"Error: E2B API returned {exc.code}: {detail}", err=True)
        raise SystemExit(1) from exc
    except urllib.error.URLError as exc:
        click.echo(f"Error: Failed to reach E2B API: {exc.reason}", err=True)
        raise SystemExit(1) from exc


@cli.group()
def webhook() -> None:
    """Manage E2B lifecycle webhooks."""


@webhook.command("register")
@click.argument("url")
@click.option(
    "--secret",
    default=None,
    help="Webhook signature secret [env: SANDSTORM_WEBHOOK_SECRET].",
)
@click.option("--e2b-api-key", default=None, help="E2B API key [env: E2B_API_KEY].")
@click.option("--no-save", is_flag=True, help="Don't write secret to .env file.")
def webhook_register(url: str, secret: str | None, e2b_api_key: str | None, no_save: bool) -> None:
    """Register an E2B lifecycle webhook.

    URL is the public endpoint (e.g. https://your-server.com/webhooks/e2b).
    """
    load_dotenv()
    api_key = _get_e2b_api_key(e2b_api_key)

    if not url.rstrip("/").endswith("/webhooks/e2b"):
        url = url.rstrip("/") + "/webhooks/e2b"
        click.echo(f"Using webhook URL: {url}", err=True)

    secret = secret or os.environ.get("SANDSTORM_WEBHOOK_SECRET", "")
    if not secret:
        secret = secrets.token_hex(32)
        click.echo(f"Generated webhook secret: {secret}", err=True)
        click.echo("Save this secret securely — it won't be shown again", err=True)

    payload: dict = {
        "name": "sandstorm",
        "url": url,
        "enabled": True,
        "signatureSecret": secret,
        "events": [
            "sandbox.lifecycle.created",
            "sandbox.lifecycle.updated",
            "sandbox.lifecycle.killed",
        ],
    }

    result = _webhook_request("POST", "", api_key, payload)
    click.echo(f"Webhook registered: {json.dumps(result, indent=2)}")

    if not no_save:
        from dotenv import set_key

        env_path = str(Path.cwd() / ".env")
        set_key(env_path, "SANDSTORM_WEBHOOK_SECRET", secret)
        click.echo("Saved SANDSTORM_WEBHOOK_SECRET to .env", err=True)


@webhook.command("list")
@click.option("--e2b-api-key", default=None, help="E2B API key [env: E2B_API_KEY].")
def webhook_list(e2b_api_key: str | None) -> None:
    """List registered E2B webhooks."""
    load_dotenv()
    api_key = _get_e2b_api_key(e2b_api_key)
    result = _webhook_request("GET", "", api_key)

    if not result:
        click.echo("No webhooks registered.")
        return

    for wh in result if isinstance(result, list) else [result]:
        click.echo(
            f"  {wh.get('id', '?')}  {wh.get('name', '?'):20s}  "
            f"{wh.get('url', '?')}  enabled={wh.get('enabled', '?')}"
        )


@webhook.command("delete")
@click.argument("webhook_id")
@click.option("--e2b-api-key", default=None, help="E2B API key [env: E2B_API_KEY].")
def webhook_delete(webhook_id: str, e2b_api_key: str | None) -> None:
    """Delete an E2B webhook by ID."""
    load_dotenv()
    api_key = _get_e2b_api_key(e2b_api_key)
    _webhook_request("DELETE", f"/{webhook_id}", api_key)
    click.echo(f"Webhook {webhook_id} deleted.")


@webhook.command("test")
@click.argument("url")
@click.option(
    "--secret",
    default=None,
    help="Webhook signature secret [env: SANDSTORM_WEBHOOK_SECRET].",
)
def webhook_test(url: str, secret: str | None) -> None:
    """Send a test event to a webhook endpoint to verify it's reachable."""
    load_dotenv()
    secret = secret or os.environ.get("SANDSTORM_WEBHOOK_SECRET", "")

    payload = json.dumps(
        {
            "type": "sandbox.lifecycle.test",
            "sandboxId": "test-sandbox-000",
            "eventData": {"sandbox_metadata": {"request_id": "test0000"}},
        }
    ).encode()

    headers = {"Content-Type": "application/json"}
    if secret:
        import hashlib
        import hmac

        sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        headers["e2b-signature"] = f"sha256={sig}"

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode(errors="replace")
            click.echo(f"✓ {resp.status}: {body}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        click.echo(f"✗ {exc.code}: {detail}", err=True)
        raise SystemExit(1) from exc
    except urllib.error.URLError as exc:
        click.echo(f"✗ Unreachable: {exc.reason}", err=True)
        raise SystemExit(1) from exc


# ── Slack bot ─────────────────────────────────────────────────────────────────


@cli.group()
def slack() -> None:
    """Sandstorm Slack bot."""


@slack.command("setup")
def slack_setup() -> None:
    """Interactive setup wizard — creates Slack app and saves tokens to .env."""
    import urllib.parse
    import webbrowser

    load_dotenv()

    # Try multiple locations: package data, repo root relative to source, CWD
    candidates = [
        Path(__file__).resolve().parent / "slack-manifest.yaml",  # package data
        Path(__file__).resolve().parent.parent.parent / "slack-manifest.yaml",  # repo root
        Path.cwd() / "slack-manifest.yaml",  # CWD
    ]
    manifest_path = next((p for p in candidates if p.exists()), None)
    if manifest_path is None:
        click.echo("Error: slack-manifest.yaml not found", err=True)
        raise SystemExit(1)

    manifest_content = manifest_path.read_text()

    click.echo("\n  Sandstorm Slack Bot Setup")
    click.echo("  " + "-" * 25 + "\n")

    # Step 1: Open browser with manifest
    encoded = urllib.parse.quote(manifest_content)
    create_url = f"https://api.slack.com/apps?new_app=1&manifest_yaml={encoded}"

    click.echo("  Step 1: Create your Slack app (opens browser)")
    click.echo(f"  -> {create_url[:80]}...")
    click.echo()
    click.echo('  Select your workspace and click "Create".')
    click.echo('  Then click "Install to Workspace" and approve.\n')

    try:
        webbrowser.open(create_url)
    except Exception:
        click.echo("  (Could not open browser — use the URL above)\n", err=True)

    # Step 2: Collect tokens
    click.echo("  Step 2: Copy your tokens\n")

    bot_token = click.prompt("  Bot Token (xoxb-...)", type=str).strip()
    if not bot_token.startswith("xoxb-"):
        click.echo("Error: Bot token should start with 'xoxb-'", err=True)
        raise SystemExit(1)

    app_token = click.prompt("  App Token (xapp-...)", type=str).strip()
    if not app_token.startswith("xapp-"):
        click.echo("Error: App token should start with 'xapp-'", err=True)
        raise SystemExit(1)

    # Step 3: Test connectivity
    try:
        from slack_sdk import WebClient

        client = WebClient(token=bot_token)
        auth = client.auth_test()
        team = auth.get("team", "unknown")
        bot_user = auth.get("user", "unknown")
        click.echo(f'\n  Connected to workspace "{team}"')
        click.echo(f"  Bot user: @{bot_user}\n")

        # Hint about setting a profile photo
        icon_path = Path(__file__).resolve().parent / "assets" / "sandstorm-icon.png"
        if icon_path.exists():
            click.echo("  Tip: Set a bot icon at your app's Basic Information page:")
            click.echo("  https://api.slack.com/apps → Display Information → App Icon")
            click.echo(f"  Icon bundled at: {icon_path}\n")
    except ImportError:
        click.echo(
            "\n  Warning: slack-sdk not installed — skipping connectivity test.",
            err=True,
        )
        click.echo('  Install with: pip install "duvo-sandstorm[slack]"\n', err=True)
    except Exception as exc:
        click.echo(f"\n  Warning: Could not verify token: {exc}", err=True)

    # Step 4: Save to .env
    from dotenv import set_key

    env_path = str(Path.cwd() / ".env")
    set_key(env_path, "SLACK_BOT_TOKEN", bot_token)
    set_key(env_path, "SLACK_APP_TOKEN", app_token)
    click.echo("  Saved SLACK_BOT_TOKEN and SLACK_APP_TOKEN to .env\n")

    # Step 5: Optionally start
    if click.confirm("  Start the bot now?", default=True):
        click.echo()
        _do_slack_start_socket()


@slack.command("start")
@click.option("--http", "use_http", is_flag=True, help="Use HTTP mode instead of Socket Mode.")
@click.option("--host", default="0.0.0.0", help="Bind address (HTTP mode).")
@click.option("--port", "-p", default=3000, type=int, help="Bind port (HTTP mode).")
def slack_start(use_http: bool, host: str, port: int) -> None:
    """Start the Slack bot."""
    load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format=_LOG_FORMAT,
        datefmt=_LOG_DATEFMT,
        stream=sys.stderr,
    )

    if use_http:
        try:
            from .slack import run_http_mode

            run_http_mode(host=host, port=port)
        except ImportError as exc:
            click.echo(
                "Error: Slack dependencies not installed."
                ' Run: pip install "duvo-sandstorm[slack]"',
                err=True,
            )
            raise SystemExit(1) from exc
    else:
        _do_slack_start_socket()


def _do_slack_start_socket() -> None:
    """Start the Slack bot in Socket Mode."""
    try:
        from .slack import run_socket_mode

        run_socket_mode()
    except ImportError as exc:
        click.echo(
            'Error: Slack dependencies not installed. Run: pip install "duvo-sandstorm[slack]"',
            err=True,
        )
        raise SystemExit(1) from exc
    except KeyboardInterrupt as exc:
        click.echo("Interrupted.", err=True)
        raise SystemExit(130) from exc
