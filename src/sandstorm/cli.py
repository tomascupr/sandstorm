"""CLI interface for Sandstorm — run the server or execute one-off queries."""

import asyncio
import json
import logging
import sys
from pathlib import Path

import click
from dotenv import load_dotenv

from sandstorm import __version__


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
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )

    from .models import QueryRequest
    from .sandbox import run_agent_in_sandbox

    files: dict[str, str] | None = None
    if file_paths:
        files = {}
        for fp in file_paths:
            p = Path(fp)
            try:
                files[p.name] = p.read_text()
            except UnicodeDecodeError:
                click.echo(f"Error: {p.name} is not a text file", err=True)
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
