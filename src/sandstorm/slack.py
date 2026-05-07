"""Slack bot integration for Sandstorm — run agents via @mentions and DMs."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING

from .memory import memory_store
from .store import run_store
from .platform import (
    BINARY_MIME_PREFIXES as _BINARY_MIME_PREFIXES,
    MAX_FILE_SIZE as _MAX_FILE_SIZE,
    SandboxPoolManager,
    StreamBridge,
    build_query_request as _build_query_request,
    gather_thread_context as _gather_thread_context,
    unique_filename as _unique_filename,
)

if TYPE_CHECKING:
    from slack_bolt.async_app import AsyncApp

logger = logging.getLogger(__name__)


# ── Metadata blocks ──────────────────────────────────────────────────────────


def _build_metadata_blocks(
    run_id: str,
    model: str | None,
    cost_usd: float | None,
    num_turns: int | None,
    duration_secs: float | None,
) -> list[dict]:
    """Block Kit footer: context line (model|turns|cost|duration) + feedback buttons."""
    parts = []
    if model:
        parts.append(f"Model: {model}")
    if num_turns is not None:
        parts.append(f"Turns: {num_turns}")
    if cost_usd is not None:
        parts.append(f"Cost: ${cost_usd:.4f}")
    if duration_secs is not None:
        parts.append(f"Duration: {duration_secs:.1f}s")

    blocks: list[dict] = []
    if parts:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": " | ".join(parts)}],
            }
        )
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "\U0001f44d Helpful"},
                    "action_id": "sandstorm_feedback_positive",
                    "value": run_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "\U0001f44e Not helpful"},
                    "action_id": "sandstorm_feedback_negative",
                    "value": run_id,
                },
            ],
        }
    )
    return blocks


# ── Thread helpers ────────────────────────────────────────────────────────────


async def _fetch_thread_messages(client, channel: str, thread_ts: str) -> list[dict]:
    """Fetch all messages in a thread via conversations_replies().

    Uses cursor-based pagination to handle threads with >200 messages.
    Returns the raw messages list, or [] on error.
    """
    try:
        messages: list[dict] = []
        cursor = None
        while True:
            kwargs: dict = {"channel": channel, "ts": thread_ts, "limit": 200}
            if cursor:
                kwargs["cursor"] = cursor
            result = await client.conversations_replies(**kwargs)
            messages.extend(result.get("messages", []))
            cursor = result.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
        return messages
    except Exception:
        logger.warning("Failed to fetch thread replies", exc_info=True)
        return []


async def _resolve_user_names(client, messages: list[dict], bot_user_id: str) -> dict[str, str]:
    """Resolve Slack user IDs to display names.

    Returns {uid: display_name} mapping. Falls back to uid on API error.
    Uses asyncio.gather() to resolve all users concurrently.
    """
    uids = {
        msg.get("user", "")
        for msg in messages
        if msg.get("user") and msg.get("user") != bot_user_id
    }

    async def _resolve(uid: str) -> tuple[str, str]:
        try:
            resp = await client.users_info(user=uid)
            profile = resp.get("user", {}).get("profile", {})
            return uid, profile.get("display_name") or profile.get("real_name") or uid
        except Exception:
            logger.warning("Failed to resolve user name for %s", uid)
            return uid, uid

    results = await asyncio.gather(*(_resolve(uid) for uid in uids))
    return dict(results)


# ── File handling ─────────────────────────────────────────────────────────────


async def _download_thread_files(
    client, messages: list[dict], bot_user_id: str
) -> tuple[dict[str, str], dict[str, bytes]]:
    """Download files shared in the thread.

    Returns (text_files, binary_files):
      - text_files: {filename: str_content} for QueryRequest.files
      - binary_files: {filename: bytes_content} for sandbox upload
    Skips files > 50MB.
    """
    try:
        import aiohttp
    except ImportError:
        logger.warning("aiohttp not available for file downloads")
        return {}, {}

    text_files: dict[str, str] = {}
    binary_files: dict[str, bytes] = {}
    seen: set[str] = set()

    headers = {"Authorization": f"Bearer {client.token}"}
    async with aiohttp.ClientSession(headers=headers) as session:
        for msg in messages:
            if msg.get("user") == bot_user_id:
                continue

            for f in msg.get("files", []):
                raw_name = f.get("name", "unknown")
                name = _unique_filename(raw_name, seen)
                mimetype = f.get("mimetype", "")
                size = f.get("size", 0)
                is_binary = any(mimetype.startswith(prefix) for prefix in _BINARY_MIME_PREFIXES)

                # Skip large files
                if size > _MAX_FILE_SIZE:
                    logger.warning("Skipping large file: %s (%d bytes)", name, size)
                    continue

                url = f.get("url_private_download") or f.get("url_private")
                if not url:
                    continue

                # Text files: try files_info API first (returns content directly)
                if not is_binary:
                    try:
                        resp = await client.files_info(file=f["id"])
                        content_resp = resp.get("content")
                        if content_resp:
                            text_files[name] = content_resp
                            continue
                    except Exception:
                        pass

                # Download via URL with bot token auth
                try:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            if is_binary:
                                binary_files[name] = await resp.read()
                            else:
                                text_files[name] = await resp.text()
                        else:
                            logger.warning("Failed to download %s: HTTP %d", name, resp.status)
                except Exception:
                    logger.warning("Failed to download file: %s", name, exc_info=True)

    return text_files, binary_files


# ── Event mapping / streaming bridge ──────────────────────────────────────────


async def _stream_to_slack(
    request: QueryRequest,
    run_id: str,
    streamer,
    client,
    channel: str,
    thread_ts: str,
    set_status: Callable | None = None,
    *,
    keep_alive: bool = False,
    sandbox_id: str | None = None,
    sandbox_id_out: list[str] | None = None,
    binary_files: dict[str, bytes] | None = None,
) -> dict:
    """Core bridge: consume run_agent_in_sandbox() -> stream to Slack."""

    def _build_footer(run_id: str, metadata: dict) -> list[dict]:
        return _build_metadata_blocks(
            run_id, metadata["model"], metadata["cost_usd"],
            metadata["num_turns"], metadata["duration_secs"],
        )

    async def _upload_file(*, channel, thread_ts, content, filename, title):
        await client.files_upload_v2(
            channel=channel, thread_ts=thread_ts,
            content=content, filename=filename, title=title,
        )

    bridge = StreamBridge(streamer, run_store=run_store)
    return await bridge.run(
        request, run_id, client, channel, thread_ts,
        set_status=set_status,
        keep_alive=keep_alive,
        sandbox_id=sandbox_id,
        sandbox_id_out=sandbox_id_out,
        binary_files=binary_files,
        build_footer=_build_footer,
        upload_file=_upload_file,
    )


# ── App factory ───────────────────────────────────────────────────────────────


def create_slack_app(
    *,
    bot_token: str | None = None,
    signing_secret: str | None = None,
    process_before_response: bool = False,
) -> AsyncApp:
    """Create and configure the Slack Bolt AsyncApp."""
    from slack_bolt.async_app import AsyncApp
    from slack_bolt.middleware.assistant.async_assistant import AsyncAssistant

    token = bot_token or os.environ.get("SLACK_BOT_TOKEN")
    app = AsyncApp(
        token=token,
        signing_secret=signing_secret,
        process_before_response=process_before_response,
    )

    # Sandbox reuse pool: (team_id, channel, thread_ts) -> (sandbox_id, lock).
    # Lock serializes concurrent @mentions in the same thread.
    _sandbox_pool = SandboxPoolManager()

    # Per-user-per-channel model override from /model. In-memory only:
    # intentionally lost on restart so overrides don't outlive the process.
    _thread_model_overrides: dict[tuple[str, str, str], str] = {}

    # ── Shared helpers (close over _sandbox_pool) ──

    async def _prepare_prompt(
        client,
        channel: str,
        thread_ts: str,
        bot_user_id: str,
        prompt: str,
        team_id: str | None = None,
        user_id: str | None = None,
    ) -> tuple[QueryRequest, dict[str, bytes]]:
        """Fetch thread context, resolve names, download files, build request."""
        messages = await _fetch_thread_messages(client, channel, thread_ts)
        user_names = await _resolve_user_names(client, messages, bot_user_id)
        thread_context = _gather_thread_context(messages, bot_user_id, user_names=user_names)
        text_files, binary_files = await _download_thread_files(client, messages, bot_user_id)

        full_prompt = prompt
        if thread_context:
            full_prompt = f"Thread context:\n{thread_context}\n\nUser request: {prompt}"

        all_files = list(text_files.keys()) + list(binary_files.keys())
        if all_files:
            file_list = "\n".join(f"- /home/user/{f}" for f in all_files)
            full_prompt += f"\n\nFiles available in your working directory:\n{file_list}"

        model_override = _thread_model_overrides.get(
            (team_id or "", channel, f"user:{user_id or ''}")
        )
        # Per-channel overlay (model / starter / allowed_tools). Explicit user
        # overrides via /model still win because they are applied afterwards.
        from .channels import resolve_channel_config
        from .config import load_sandstorm_config

        overlay = resolve_channel_config(load_sandstorm_config(), channel)
        overlay_model = overlay.get("model") if overlay else None
        overlay_allowed_tools = overlay.get("allowed_tools") if overlay else None
        request = _build_query_request(
            full_prompt,
            text_files or None,
            team_id=team_id,
            user_id=user_id,
            model=model_override or overlay_model,
            channel_id=channel,
        )
        if overlay_allowed_tools is not None and request.allowed_tools is None:
            request.allowed_tools = list(overlay_allowed_tools)

        prior_run = run_store.find_thread_session(team_id, channel, thread_ts)
        if prior_run and prior_run.agent_session_id:
            request.resume = prior_run.agent_session_id

        return request, binary_files

    async def _run_in_sandbox_pool(
        *,
        request: QueryRequest,
        run_id: str,
        client,
        channel: str,
        thread_ts: str,
        context,
        user_id: str,
        binary_files: dict[str, bytes],
        set_status: Callable | None = None,
    ) -> dict:
        """Run agent with sandbox reuse, pool management, and eviction."""
        tenant = context.get("enterprise_id") or context.get("team_id") or ""

        if not _sandbox_pool.has_key(tenant, channel, thread_ts):
            prior = run_store.find_thread_session(tenant, channel, thread_ts)
            initial_id = prior.sandbox_id if prior else None
            _sandbox_pool.set_initial(tenant, channel, thread_ts, initial_id)

        existing_sandbox_id, lock = await _sandbox_pool.get_or_create(tenant, channel, thread_ts)

        async with lock:
            # Re-read after acquiring lock (another coroutine may have updated it)
            existing_sandbox_id, _ = await _sandbox_pool.get_or_create(tenant, channel, thread_ts)
            sandbox_id_out: list[str] = []
            reuse_succeeded = False
            if existing_sandbox_id:
                logger.info(
                    "[%s] Reusing sandbox %s for thread %s",
                    run_id,
                    existing_sandbox_id,
                    thread_ts,
                )
                streamer = await client.chat_stream(
                    channel=channel,
                    thread_ts=thread_ts,
                    recipient_team_id=context.get("team_id"),
                    recipient_user_id=user_id,
                )
                metadata = await _stream_to_slack(
                    request,
                    run_id,
                    streamer,
                    client,
                    channel,
                    thread_ts,
                    set_status=set_status,
                    keep_alive=True,
                    sandbox_id=existing_sandbox_id,
                    binary_files=binary_files or None,
                )
                reuse_succeeded = not metadata.get("error")
                if not reuse_succeeded:
                    _sandbox_pool.clear(tenant, channel, thread_ts)
                    logger.warning(
                        "[%s] Sandbox %s failed, creating new",
                        run_id,
                        existing_sandbox_id,
                    )

            if not reuse_succeeded:
                if existing_sandbox_id:
                    # Fresh run_id for the retry — the failed reuse attempt
                    # already recorded its own run entry and Slack message.
                    run_id = uuid.uuid4().hex[:8]

                streamer = await client.chat_stream(
                    channel=channel,
                    thread_ts=thread_ts,
                    recipient_team_id=context.get("team_id"),
                    recipient_user_id=user_id,
                )
                metadata = await _stream_to_slack(
                    request,
                    run_id,
                    streamer,
                    client,
                    channel,
                    thread_ts,
                    set_status=set_status,
                    keep_alive=True,
                    sandbox_id_out=sandbox_id_out,
                    binary_files=binary_files or None,
                )
                new_id = sandbox_id_out[0] if sandbox_id_out else None
                _sandbox_pool.update(tenant, channel, thread_ts, new_id)

        # Evict oldest entries if pool is too large
        _sandbox_pool.evict_if_needed()

        return metadata

    # ── 1. @mention handler — primary interaction in channels ──

    @app.event("app_mention")
    async def handle_mention(event, client, say, context):
        channel = event["channel"]
        thread_ts = event.get("thread_ts", event["ts"])
        user_id = event["user"]
        bot_user_id = context["bot_user_id"]

        # Extract prompt (strip @mention)
        raw_text = event.get("text", "")
        prompt = re.sub(r"<@[A-Z0-9]+>", "", raw_text).strip()
        if not prompt:
            await say(text="Mention me with a task!", thread_ts=thread_ts)
            return

        # Add :eyes: reaction as status indicator
        with contextlib.suppress(Exception):
            await client.reactions_add(channel=channel, timestamp=event["ts"], name="eyes")

        run_id = uuid.uuid4().hex[:8]
        tenant = context.get("enterprise_id") or context.get("team_id")
        request, binary_files = await _prepare_prompt(
            client,
            channel,
            thread_ts,
            bot_user_id,
            prompt,
            team_id=tenant,
            user_id=user_id,
        )
        await _run_in_sandbox_pool(
            request=request,
            run_id=run_id,
            client=client,
            channel=channel,
            thread_ts=thread_ts,
            context=context,
            user_id=user_id,
            binary_files=binary_files,
        )

        # Remove :eyes: reaction on completion
        with contextlib.suppress(Exception):
            await client.reactions_remove(channel=channel, timestamp=event["ts"], name="eyes")

    # ── 2. Assistant DM handler — conversational thread experience ──

    assistant = AsyncAssistant()

    @assistant.thread_started
    async def handle_thread_started(say, set_suggested_prompts):
        await say(
            "Hi! I'm Sandstorm — I run general-purpose agent tasks in secure sandboxes. "
            "What should I help with?"
        )
        await set_suggested_prompts(
            prompts=[
                {
                    "title": "Analyze a file",
                    "message": "Analyze the attached file...",
                },
                {
                    "title": "Compare options",
                    "message": "Compare these competitor pages...",
                },
                {
                    "title": "Draft content",
                    "message": "Draft a summary from this document...",
                },
            ]
        )

    @assistant.user_message
    async def handle_user_message(payload, client, say, set_status, context):
        channel_id = context.channel_id
        thread_ts = context.thread_ts
        user_id = payload.get("user", "unknown")
        bot_user_id = context.get("bot_user_id", "")
        prompt = payload.get("text", "")
        if not prompt.strip():
            await say("Please provide a prompt.")
            return

        # bolt-python 1.28 lets set_status rotate through a list of loading
        # messages so the user sees visible progress instead of a single static
        # status. Fall through to the positional form on older bolt versions.
        try:
            await set_status(
                status="Spinning up sandbox...",
                loading_messages=[
                    "Warming up the sandbox...",
                    "Pulling thread context...",
                    "Running tools...",
                    "Writing the answer...",
                ],
            )
        except TypeError:
            await set_status("Spinning up sandbox...")
        run_id = uuid.uuid4().hex[:8]
        tenant = context.get("enterprise_id") or context.get("team_id")
        request, binary_files = await _prepare_prompt(
            client,
            channel_id,
            thread_ts,
            bot_user_id,
            prompt,
            team_id=tenant,
            user_id=user_id,
        )
        await _run_in_sandbox_pool(
            request=request,
            run_id=run_id,
            client=client,
            channel=channel_id,
            thread_ts=thread_ts,
            context=context,
            user_id=user_id,
            binary_files=binary_files,
            set_status=set_status,
        )

    app.use(assistant)

    # ── 3. Feedback action handlers ──

    async def _handle_feedback(ack, body, client, *, sentiment: str, emoji: str, label: str):
        await ack()
        run_id = body["actions"][0]["value"]
        user = body["user"]["id"]
        run_store.set_feedback(run_id, sentiment, user)

        # Replace buttons with confirmation
        message = body.get("message", {})
        channel = body["channel"]["id"]
        ts = message.get("ts")
        blocks = message.get("blocks", [])
        updated_blocks = [b for b in blocks if b.get("type") != "actions"]
        updated_blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"{emoji} <@{user}> {label}"}],
            }
        )
        if ts:
            await client.chat_update(
                channel=channel, ts=ts, blocks=updated_blocks, text="Feedback recorded"
            )

    @app.action("sandstorm_feedback_positive")
    async def handle_positive(ack, body, client):
        await _handle_feedback(
            ack, body, client, sentiment="positive", emoji="\U0001f44d", label="found this helpful"
        )

    @app.action("sandstorm_feedback_negative")
    async def handle_negative(ack, body, client):
        await _handle_feedback(
            ack,
            body,
            client,
            sentiment="negative",
            emoji="\U0001f44e",
            label="found this not helpful",
        )

    # ── 4. Memory + model slash commands ──
    #
    # /remember <text>           persist a fact for (team_id, user_id)
    # /forget <substring>        tombstone memories containing substring
    # /memories                  list live memories
    # /model <name>              override the model for this thread until restart
    #
    # All four are scoped to (team_id, user_id). Slack requires the `commands`
    # bot scope for these to appear in the workspace — see slack-manifest.yaml.

    def _command_scope(command) -> tuple[str | None, str | None]:
        # On Enterprise Grid, the bot is installed on the enterprise and the
        # sub-workspace team_id rotates per channel. Prefer enterprise_id so
        # memories stay scoped to the whole tenant; fall back to team_id for
        # single-workspace installs where enterprise_id is absent.
        tenant = command.get("enterprise_id") or command.get("team_id")
        return tenant, command.get("user_id")

    def _parse_scope_filter(text: str) -> tuple[str, str | None]:
        """Split `/memories team` or `/forget foo channel` into (remainder, scope)."""
        stripped = text.strip()
        for word in ("team", "channel", "user"):
            if stripped == word:
                return "", word
            if stripped.startswith(word + " "):
                return stripped[len(word) + 1 :].strip(), word
            if stripped.endswith(" " + word):
                return stripped[: -(len(word) + 1)].strip(), word
        return stripped, None

    @app.command("/remember")
    async def handle_remember(ack, command, respond):
        await ack()
        text = (command.get("text") or "").strip()
        if not text:
            await respond(text="Usage: `/remember <fact>`. Example: `/remember likes oat milk`.")
            return
        team_id, user_id = _command_scope(command)
        memory_store.remember(team_id, user_id, text, scope="user")
        await respond(text=f"Remembered (user): _{text}_")

    @app.command("/team-remember")
    async def handle_team_remember(ack, command, respond):
        await ack()
        text = (command.get("text") or "").strip()
        if not text:
            await respond(
                text="Usage: `/team-remember <fact>`. Example: `/team-remember we ship to Berlin`."
            )
            return
        team_id, user_id = _command_scope(command)
        memory_store.remember(team_id, user_id, text, scope="team")
        await respond(text=f"Remembered (team): _{text}_")

    @app.command("/channel-remember")
    async def handle_channel_remember(ack, command, respond):
        await ack()
        text = (command.get("text") or "").strip()
        channel_id = command.get("channel_id") or ""
        if not text:
            await respond(
                text=(
                    "Usage: `/channel-remember <fact>`. "
                    "Visible to everyone who uses Sandstorm in this channel."
                )
            )
            return
        if not channel_id:
            await respond(text="Channel-scoped memory requires a channel context.")
            return
        team_id, user_id = _command_scope(command)
        memory_store.remember(team_id, user_id, text, scope="channel", channel_id=channel_id)
        await respond(text=f"Remembered (channel): _{text}_")

    @app.command("/forget")
    async def handle_forget(ack, command, respond):
        await ack()
        raw = (command.get("text") or "").strip()
        substring, scope_filter = _parse_scope_filter(raw)
        if not substring:
            await respond(
                text=(
                    "Usage: `/forget <substring> [user|channel|team]`. "
                    "Omit the scope to match all visible memories."
                )
            )
            return
        team_id, user_id = _command_scope(command)
        channel_id = command.get("channel_id") or None
        deleted = memory_store.forget(
            team_id,
            user_id,
            substring,
            scope=scope_filter,  # type: ignore[arg-type]
            channel_id=channel_id,
        )
        if deleted:
            await respond(text=f"Forgot {deleted} memor{'y' if deleted == 1 else 'ies'}.")
        else:
            await respond(text=f"No memory matched `{substring}`.")

    @app.command("/memories")
    async def handle_memories(ack, command, respond):
        await ack()
        raw = (command.get("text") or "").strip()
        _, scope_filter = _parse_scope_filter(raw)
        team_id, user_id = _command_scope(command)
        channel_id = command.get("channel_id") or None
        memories = memory_store.list(
            team_id,
            user_id,
            scope=scope_filter,  # type: ignore[arg-type]
            channel_id=channel_id,
        )
        if not memories:
            await respond(text="No memories yet. Use `/remember <fact>` to add one.")
            return
        lines = [f"{i + 1}. [{m.scope}] {m.text}" for i, m in enumerate(memories)]
        header = (
            "Your memories" if scope_filter is None else f"{scope_filter.capitalize()} memories"
        )
        await respond(text=f"{header}:\n" + "\n".join(lines))

    @app.command("/model")
    async def handle_model(ack, command, respond):
        await ack()
        # Slash commands do not carry thread_ts, so /model scopes to
        # (tenant, channel, user) instead of per-thread. The override then
        # applies to that user's next @mention or DM in this channel.
        model = (command.get("text") or "").strip()
        tenant = command.get("enterprise_id") or command.get("team_id") or ""
        channel = command.get("channel_id") or ""
        user_id = command.get("user_id") or ""
        key = (tenant, channel, f"user:{user_id}")
        if not model:
            current = _thread_model_overrides.get(key)
            await respond(
                text=(
                    f"Current model override in this channel: `{current}`"
                    if current
                    else "No model override set in this channel."
                )
                + " Pass a model name to set one: `/model claude-haiku-4-5-20251001`."
            )
            return
        if model.lower() in {"clear", "reset", "none"}:
            _thread_model_overrides.pop(key, None)
            await respond(text="Cleared model override. Will use the configured default.")
            return
        _thread_model_overrides[key] = model
        await respond(text=f"Model override set for this channel: `{model}`")

    @app.command("/cancel")
    async def handle_cancel(ack, command, respond):
        await ack()
        from .cancellation import request_cancellation

        tenant = command.get("enterprise_id") or command.get("team_id")
        channel = command.get("channel_id") or ""
        invoker = command.get("user_id") or ""
        # Scope the lookup to the invoking user so two users sharing a channel
        # don't cancel each other's runs by accident.
        run = run_store.find_most_recent(
            lambda r: (
                r.team_id == tenant
                and r.channel_id == channel
                and r.user_id == invoker
                and r.status == "running"
            )
        )
        if run is None:
            await respond(text="You have no in-flight run to cancel in this channel.")
            return
        if request_cancellation(run.id):
            await respond(text=f"Cancelled run `{run.id}`.")
        else:
            await respond(
                text=f"Run `{run.id}` has no active cancellation event (already finishing)."
            )

    # ── 4.5 App Home tab ──────────────────────────────────────────────────────

    @app.event("app_home_opened")
    async def handle_app_home_opened(event, client, context):
        from .app_home import publish_home_view

        tenant = context.get("enterprise_id") or context.get("team_id")
        await publish_home_view(client, user_id=event.get("user", ""), team_id=tenant)

    @app.action("sandstorm_forget_memory")
    async def handle_forget_memory_action(ack, body, client, context):
        await ack()
        from .app_home import publish_home_view

        memory_id = body.get("actions", [{}])[0].get("value") or ""
        tenant = context.get("enterprise_id") or context.get("team_id")
        user_id = (body.get("user") or {}).get("id") or ""
        # Ownership check: only forget the clicking user's own memory. Without
        # this, any user who can open App Home could delete another user's
        # memory by crafting an action payload with that memory id.
        if memory_id:
            memory_store.forget_by_id(memory_id, team_id=tenant, user_id=user_id, scope="user")
        await publish_home_view(client, user_id=user_id, team_id=tenant)

    @app.action("sandstorm_cancel_run")
    async def handle_cancel_run_action(ack, body, client, context):
        await ack()
        from .app_home import publish_home_view
        from .cancellation import request_cancellation

        run_id = body.get("actions", [{}])[0].get("value") or ""
        tenant = context.get("enterprise_id") or context.get("team_id")
        user_id = (body.get("user") or {}).get("id") or ""
        # Ownership check: only cancel runs that belong to the clicking user
        # in their own tenant.
        if run_id:
            run = run_store.get(run_id)
            if (
                run is not None
                and run.team_id == tenant
                and run.user_id == user_id
                and run.status == "running"
            ):
                request_cancellation(run_id)
        await publish_home_view(client, user_id=user_id, team_id=tenant)

    # ── 5. Reaction-triggered runs ─────────────────────────────────────────────
    # Users add an emoji to a message to fire an agent. Matched against
    # reaction-type triggers in sandstorm.json. Runs land in the same thread
    # as the reacted-to message so they share the paused sandbox.

    @app.event("reaction_added")
    async def handle_reaction(event, client, context):
        emoji = event.get("reaction")
        item = event.get("item") or {}
        if item.get("type") != "message":
            return
        channel = item.get("channel")
        ts = item.get("ts")
        if not channel or not ts:
            return

        from .config import load_sandstorm_config
        from .triggers import load_triggers, render_prompt

        config = load_sandstorm_config()
        if config is None:
            return
        try:
            triggers = load_triggers(config)
        except ValueError:
            logger.exception("Failed to load triggers for reaction event")
            return

        matches = [
            t
            for t in triggers
            if t.type == "reaction"
            and t.emoji == emoji
            and (not t.channels or channel in t.channels)
        ]
        if not matches:
            return

        try:
            history = await client.conversations_history(
                channel=channel, oldest=ts, inclusive=True, limit=1
            )
        except Exception:
            logger.exception("Failed to fetch reacted-to message %s/%s", channel, ts)
            return
        messages = history.get("messages", []) if history else []
        if not messages:
            return
        message = messages[0]

        tenant = context.get("enterprise_id") or context.get("team_id")
        user_id = event.get("user", "unknown")

        for trigger in matches:
            rendered = render_prompt(
                trigger.prompt,
                message={"text": message.get("text", ""), "user": message.get("user", "")},
                channel={"id": channel},
                reaction=emoji,
            )
            run_id = uuid.uuid4().hex[:8]
            request = _build_query_request(rendered, None, team_id=tenant, user_id=user_id)
            thread_ts = message.get("thread_ts") or ts
            try:
                await _run_in_sandbox_pool(
                    request=request,
                    run_id=run_id,
                    client=client,
                    channel=channel,
                    thread_ts=thread_ts,
                    context=context,
                    user_id=user_id,
                    binary_files={},
                )
            except Exception:
                logger.exception("Reaction trigger %s failed for run %s", trigger.name, run_id)

    return app


# ── CLI entrypoints ───────────────────────────────────────────────────────────


def run_socket_mode(bot_token: str | None = None, app_token: str | None = None) -> None:
    """Start bot in Socket Mode (dev — no public URL needed)."""
    from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

    app = create_slack_app(bot_token=bot_token)
    app_token = app_token or os.environ.get("SLACK_APP_TOKEN")
    if not app_token:
        raise RuntimeError(
            "SLACK_APP_TOKEN is required for Socket Mode — set it in .env or pass via --app-token"
        )

    logger.info("Starting Sandstorm Slack bot in Socket Mode...")

    async def _start():
        handler = AsyncSocketModeHandler(app, app_token)
        await handler.start_async()

    asyncio.run(_start())


def run_http_mode(
    bot_token: str | None = None,
    signing_secret: str | None = None,
    host: str = "0.0.0.0",
    port: int = 3000,
) -> None:
    """Start bot in HTTP mode (production)."""
    import uvicorn
    from slack_bolt.adapter.starlette.async_handler import AsyncSlackRequestHandler
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    secret = signing_secret or os.environ.get("SLACK_SIGNING_SECRET")
    app = create_slack_app(bot_token=bot_token, signing_secret=secret)
    app_handler = AsyncSlackRequestHandler(app)

    async def endpoint(req: Request):
        return await app_handler.handle(req)

    async def health(req: Request):
        return JSONResponse({"status": "ok"})

    starlette_app = Starlette(
        routes=[
            Route("/slack/events", endpoint=endpoint, methods=["POST"]),
            Route("/health", endpoint=health, methods=["GET"]),
        ]
    )
    logger.info("Starting Sandstorm Slack bot in HTTP mode on %s:%d", host, port)
    uvicorn.run(starlette_app, host=host, port=port)
