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
from sandstorm.e2b_api import E2BApiError, webhook_request
from sandstorm.starter_catalog import (
    StarterDefinition,
    list_starters,
    resolve_starter,
    scaffold_files,
)

_MODEL_OVERRIDE_ENV_KEYS = (
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
)


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


def _print_starter_list() -> None:
    """Print the bundled starter catalog."""
    click.echo("Available starters:\n")
    for starter in list_starters():
        click.echo(f"  {starter.slug:18s} {starter.description}")
        if starter.aliases:
            click.echo(f"  {'aliases:':18s} {', '.join(starter.aliases)}")
        click.echo()


def _prompt_for_starter() -> StarterDefinition:
    """Interactively choose a starter from the catalog."""
    _print_starter_list()
    starter_name = click.prompt(
        "Starter",
        type=click.Choice([starter.slug for starter in list_starters()], case_sensitive=False),
        default="general-assistant",
        show_choices=False,
    )
    return resolve_starter(starter_name)


def _is_empty_directory(path: Path) -> bool:
    return path.is_dir() and not any(path.iterdir())


def _suggest_destination(default_path: Path) -> Path:
    """Return the first available sibling destination."""
    for suffix in range(2, 100):
        candidate = default_path.with_name(f"{default_path.name}-{suffix}")
        if not candidate.exists():
            return candidate
    raise click.ClickException(f"Could not find an available directory name near {default_path}.")


def _prompt_for_destination(default_path: Path) -> Path:
    """Prompt until the user chooses a writable destination."""
    click.echo(
        f"Default destination {default_path} already exists and is not empty."
        " Choose a different directory."
    )
    suggestion = _suggest_destination(default_path)
    while True:
        raw_value = click.prompt("Destination directory", default=str(suggestion))
        destination = Path(raw_value).expanduser()
        if not destination.exists() or _is_empty_directory(destination):
            return destination
        click.echo(
            f"{destination} already exists and is not empty. Choose a different directory.",
            err=True,
        )


def _validate_existing_destination(destination: Path, force: bool) -> None:
    """Validate the destination root before any writes happen."""
    if destination.exists() and not destination.is_dir():
        raise click.ClickException(f"Destination {destination} exists and is not a directory.")
    if destination.exists() and not _is_empty_directory(destination) and not force:
        raise click.ClickException(
            f"Destination {destination} already exists and is not empty. "
            "Use --force to overwrite starter-managed files."
        )


def _resolve_scaffold_target(destination: Path, relative_path: str) -> Path:
    """Resolve a scaffold target and ensure it stays within the destination root."""
    destination_root = destination.resolve()
    target = (destination_root / relative_path).resolve()
    if not target.is_relative_to(destination_root):
        raise click.ClickException(
            f"Refusing to write {relative_path}: resolves outside {destination}."
        )
    return target


def _validate_scaffold_targets(destination: Path, files: dict[str, str], force: bool) -> None:
    """Validate target paths so scaffolding does not partially write files."""
    required_dirs = {destination.resolve()}
    for relative_path in files:
        required_dirs.add(_resolve_scaffold_target(destination, relative_path).parent)

    for directory in sorted(required_dirs):
        current = directory
        while True:
            if current.exists():
                if not current.is_dir():
                    raise click.ClickException(
                        f"Cannot create {directory}: {current} exists and is not a directory."
                    )
                break
            if current == current.parent:
                break
            current = current.parent

    for relative_path in sorted(files):
        target = _resolve_scaffold_target(destination, relative_path)
        if target.exists() and target.is_dir():
            raise click.ClickException(f"Cannot overwrite directory {target} with a file.")
        if target.exists() and not force:
            raise click.ClickException(
                f"Target {target} already exists. Use --force to overwrite starter-managed files."
            )


def _write_scaffold(destination: Path, files: dict[str, str]) -> None:
    """Write starter files into the destination directory."""
    destination.mkdir(parents=True, exist_ok=True)
    for relative_path, content in sorted(files.items()):
        target = _resolve_scaffold_target(destination, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _get_env_value(name: str) -> str:
    """Return a trimmed environment value or an empty string."""
    return os.environ.get(name, "").strip()


def _copy_env_values(values: dict[str, str], *names: str) -> None:
    """Copy present environment values into the target mapping."""
    for name in names:
        value = _get_env_value(name)
        if value:
            values[name] = value


def _resolve_init_env_values() -> tuple[dict[str, str], list[str]]:
    """Resolve provider-specific env vars for `ds init`."""
    values: dict[str, str] = {}
    missing: list[str] = []

    e2b_api_key = _get_env_value("E2B_API_KEY")
    if e2b_api_key:
        values["E2B_API_KEY"] = e2b_api_key
    else:
        missing.append("E2B_API_KEY")

    if _get_env_value("CLAUDE_CODE_USE_VERTEX"):
        _copy_env_values(
            values,
            "CLAUDE_CODE_USE_VERTEX",
            "CLOUD_ML_REGION",
            "ANTHROPIC_VERTEX_PROJECT_ID",
            "GOOGLE_APPLICATION_CREDENTIALS",
        )
        for name in (
            "CLOUD_ML_REGION",
            "ANTHROPIC_VERTEX_PROJECT_ID",
            "GOOGLE_APPLICATION_CREDENTIALS",
        ):
            if name not in values:
                missing.append(name)
        return values, missing

    if _get_env_value("CLAUDE_CODE_USE_BEDROCK"):
        _copy_env_values(
            values,
            "CLAUDE_CODE_USE_BEDROCK",
            "AWS_REGION",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
        )
        for name in ("AWS_REGION", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
            if name not in values:
                missing.append(name)
        return values, missing

    if _get_env_value("CLAUDE_CODE_USE_FOUNDRY"):
        _copy_env_values(
            values,
            "CLAUDE_CODE_USE_FOUNDRY",
            "AZURE_FOUNDRY_RESOURCE",
            "AZURE_API_KEY",
        )
        for name in ("AZURE_FOUNDRY_RESOURCE", "AZURE_API_KEY"):
            if name not in values:
                missing.append(name)
        return values, missing

    base_url = _get_env_value("ANTHROPIC_BASE_URL")
    openrouter_api_key = _get_env_value("OPENROUTER_API_KEY")
    if openrouter_api_key or "openrouter.ai" in base_url:
        values["ANTHROPIC_BASE_URL"] = base_url or "https://openrouter.ai/api"
        _copy_env_values(values, "OPENROUTER_API_KEY", *_MODEL_OVERRIDE_ENV_KEYS)
        if "OPENROUTER_API_KEY" not in values:
            missing.append("OPENROUTER_API_KEY")
        return values, missing

    if base_url:
        values["ANTHROPIC_BASE_URL"] = base_url
        _copy_env_values(
            values, "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", *_MODEL_OVERRIDE_ENV_KEYS
        )
        if "ANTHROPIC_AUTH_TOKEN" not in values and "ANTHROPIC_API_KEY" not in values:
            missing.append("ANTHROPIC_AUTH_TOKEN")
        return values, missing

    anthropic_api_key = _get_env_value("ANTHROPIC_API_KEY")
    if anthropic_api_key:
        values["ANTHROPIC_API_KEY"] = anthropic_api_key
    else:
        missing.append("ANTHROPIC_API_KEY")
    return values, missing


def _missing_env_names(env_values: dict[str, str], required_names: list[str]) -> list[str]:
    """Return required env names that are still unset after prompting."""
    return [name for name in required_names if not env_values.get(name)]


def _uses_default_openrouter_base_url(env_values: dict[str, str], missing: list[str]) -> bool:
    """Return True when init will write the default OpenRouter Anthropic-compatible URL."""
    return (
        not _get_env_value("ANTHROPIC_BASE_URL")
        and env_values.get("ANTHROPIC_BASE_URL") == "https://openrouter.ai/api"
        and ("OPENROUTER_API_KEY" in env_values or "OPENROUTER_API_KEY" in missing)
    )


def _maybe_prompt_for_env_file(destination: Path) -> tuple[bool, list[str]]:
    """Prompt for missing provider settings and optionally write .env."""
    env_path = destination / ".env"
    if env_path.exists():
        click.echo("Skipped .env setup because the destination already has a .env file.")
        return False, []

    env_values, missing = _resolve_init_env_values()
    if not missing:
        return False, []

    if _uses_default_openrouter_base_url(env_values, missing):
        click.echo("Using default OpenRouter base URL: https://openrouter.ai/api")

    click.echo("\nAdd the missing provider settings so this starter is runnable right away.\n")
    prompt_names = [name for name in missing if name != "E2B_API_KEY"]
    if "E2B_API_KEY" in missing:
        prompt_names.append("E2B_API_KEY")
    for name in prompt_names:
        env_values[name] = click.prompt(name, type=str).strip()

    remaining_missing = _missing_env_names(env_values, missing)
    if remaining_missing:
        click.echo(
            "Skipped .env setup because some required provider settings were left blank.",
            err=True,
        )
        return False, remaining_missing

    env_lines = [f"{name}={value}" for name, value in env_values.items() if value]
    if not env_lines:
        return False, missing
    env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    env_path.chmod(0o600)
    return True, []


def _print_init_next_steps(
    destination: Path, starter: StarterDefinition, env_written: bool, missing: list[str]
) -> None:
    """Print concise next steps after scaffolding."""
    click.echo(f"\nInitialized {starter.slug} in {destination}.")
    if env_written:
        click.echo("Wrote .env with your provider settings.")
    elif missing:
        click.echo("Fill in .env.example or create a .env with: " + ", ".join(missing) + ".")

    click.echo("\nNext steps:")
    click.echo(f"  cd {destination}")
    click.echo(f"  {starter.next_step_command}")


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
@click.argument("starter_name", required=False)
@click.argument("directory", required=False, type=click.Path(path_type=Path))
@click.option("--list", "show_list", is_flag=True, help="List available starters.")
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite starter-managed files when the destination already exists.",
)
def init(starter_name: str | None, directory: Path | None, show_list: bool, force: bool) -> None:
    """Scaffold a starter project with sandstorm.json and companion files."""
    load_dotenv()

    if show_list:
        if starter_name or directory is not None:
            raise click.UsageError("--list cannot be combined with starter arguments.")
        _print_starter_list()
        return

    interactive = starter_name is None
    if interactive:
        starter = _prompt_for_starter()
    else:
        try:
            starter = resolve_starter(starter_name or "")
        except ValueError as exc:
            raise click.BadParameter(str(exc), param_hint="starter") from exc
    default_destination = Path(starter.slug)

    if directory is not None:
        destination = directory.expanduser()
    elif interactive:
        destination = (
            default_destination
            if (
                force
                or not default_destination.exists()
                or _is_empty_directory(default_destination)
            )
            else _prompt_for_destination(default_destination)
        )
    else:
        destination = default_destination

    focus_sentence = None
    if interactive:
        focus_sentence = click.prompt(
            "What should this agent help with?",
            default="",
            show_default=False,
        ).strip()

    scaffold = scaffold_files(starter, focus_sentence)
    _validate_existing_destination(destination, force)
    _validate_scaffold_targets(destination, scaffold, force)
    _write_scaffold(destination, scaffold)
    if interactive:
        env_written, missing = _maybe_prompt_for_env_file(destination)
    elif (destination / ".env").exists():
        env_written, missing = False, []
    else:
        env_written = False
        _, missing = _resolve_init_env_values()
    _print_init_next_steps(destination, starter, env_written, missing)


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


def _cli_webhook_request(
    method: str, path: str, api_key: str, data: dict | None = None
) -> dict | list | None:
    """CLI wrapper around webhook_request that exits on error."""
    try:
        return webhook_request(method, path, api_key, data)
    except E2BApiError as exc:
        click.echo(f"Error: {exc}", err=True)
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

    result = _cli_webhook_request("POST", "", api_key, payload)
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
    result = _cli_webhook_request("GET", "", api_key)

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
    _cli_webhook_request("DELETE", f"/{webhook_id}", api_key)
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

    # Try multiple locations: package data, CWD
    candidates = [
        Path(__file__).resolve().parent / "slack-manifest.yaml",  # package data
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
