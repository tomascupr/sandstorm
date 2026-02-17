"""CLI interface for Sandstorm — run the server or execute one-off queries."""

import asyncio
import json
import logging
import os
import sys
import urllib.request
import urllib.error
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
                click.echo(
                    f"[tool: {block.get('name', 'unknown')}]", nl=False, err=True
                )

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
            except UnicodeDecodeError:
                click.echo(f"Error: {key} is not a text file", err=True)
                raise SystemExit(1)

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
        raise SystemExit(1)

    async def _run() -> None:
        async for line in run_agent_in_sandbox(request, "cli"):
            if json_output:
                click.echo(line)
            else:
                _print_event(line)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        click.echo("Interrupted.", err=True)
        raise SystemExit(130)


# ── Webhook management ─────────────────────────────────────────────────────


def _get_e2b_api_key(explicit: str | None) -> str:
    """Resolve E2B API key from flag, env, or .env file."""
    key = explicit or os.environ.get("E2B_API_KEY", "")
    if not key:
        click.echo("Error: E2B API key required (--e2b-api-key or E2B_API_KEY)", err=True)
        raise SystemExit(1)
    return key


def _webhook_request(method: str, path: str, api_key: str, data: dict | None = None) -> dict | list | None:
    """Make a request to the E2B webhook API."""
    url = f"{_E2B_WEBHOOK_API}{path}"
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        click.echo(f"Error: E2B API returned {exc.code}: {detail}", err=True)
        raise SystemExit(1)


@cli.group()
def webhook() -> None:
    """Manage E2B lifecycle webhooks."""


@webhook.command("register")
@click.argument("url")
@click.option("--secret", default=None, help="Webhook signature secret [env: SANDSTORM_WEBHOOK_SECRET].")
@click.option("--e2b-api-key", default=None, help="E2B API key [env: E2B_API_KEY].")
def webhook_register(url: str, secret: str | None, e2b_api_key: str | None) -> None:
    """Register an E2B lifecycle webhook.

    URL is the public endpoint (e.g. https://your-server.com/webhooks/e2b).
    """
    load_dotenv()
    api_key = _get_e2b_api_key(e2b_api_key)
    secret = secret or os.environ.get("SANDSTORM_WEBHOOK_SECRET", "")

    payload: dict = {
        "name": "sandstorm",
        "url": url,
        "enabled": True,
        "events": [
            "sandbox.lifecycle.created",
            "sandbox.lifecycle.updated",
            "sandbox.lifecycle.killed",
        ],
    }
    if secret:
        payload["signatureSecret"] = secret

    result = _webhook_request("POST", "", api_key, payload)
    click.echo(f"Webhook registered: {json.dumps(result, indent=2)}")


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
