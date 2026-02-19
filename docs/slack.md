# Slack Bot

Run Sandstorm agents directly in Slack. @mention in channels, DM for 1:1 conversations. Every response streams in real-time, runs in an isolated sandbox, and supports file uploads, multi-turn threads, and feedback.

## Setup

### 1. Install the Slack extra

```bash
pip install "duvo-sandstorm[slack]"
```

### 2. Create the Slack app

Run the interactive setup wizard — it opens Slack's app creation page with a pre-filled manifest, collects your tokens, and saves them to `.env`:

```bash
ds slack setup
```

The wizard will:

1. Open your browser to create the Slack app (manifest pre-filled with required scopes and events)
2. Prompt you to install the app to your workspace
3. Ask for your **Bot Token** (`xoxb-...`) and **App Token** (`xapp-...`)
4. Test connectivity and save both tokens to `.env`
5. Show where to upload a bot icon (bundled PNG included)

> **Where to find the tokens:** After creating the app, go to **OAuth & Permissions** for the Bot Token and **Basic Information > App-Level Tokens** for the App Token (create one with `connections:write` scope).

### 3. Start the bot

```bash
ds slack start
```

This starts in Socket Mode (no public URL needed — great for development). The bot connects to Slack via WebSocket and starts listening for @mentions and DMs.

## Usage

### @mentions (channels)

Mention the bot in any channel it's been invited to:

```
@Sandstorm Create a Python script that fetches the top HN stories and saves them as CSV
```

```
@Sandstorm Analyze the attached CSV and find outliers
```

The bot reacts with :eyes: while working, streams the response in the thread, and shows a metadata footer when done.

### DMs (Assistant threads)

Open a DM with the bot to start a 1:1 conversation. The bot shows suggested prompts to get started:

- "Create a Python script that..."
- "Analyze the attached file..."
- "Build a REST API with..."

Each DM thread is its own conversation with status updates ("Spinning up sandbox...", "Using Bash...").

### Threads

Thread context carries over automatically. The agent sees the full conversation history (including its own prior responses and any files shared) when you follow up in a thread:

```
User:      @Sandstorm Create a Flask API with user auth
Sandstorm: [builds the API, streams response]
User:      @Sandstorm Now add rate limiting to the /login endpoint
Sandstorm: [sees prior context, modifies the existing code]
```

## Features

- **Streaming responses** — agent output appears in real-time as it works, not all at once
- **File uploads** — share text files (code, CSV, JSON, logs) and binary files (images, PDFs, audio, video, zip) in the thread; the agent gets them in its sandbox. 10 MB limit per file
- **Sandbox reuse per thread** — follow-up @mentions in the same thread reuse the sandbox, so the agent has access to files and state from previous turns
- **Thread context** — full conversation history (including bot responses and file attachment metadata) is passed to the agent for multi-turn conversations
- **Feedback buttons** — each response gets thumbs up/down buttons; feedback is recorded in the run store
- **Metadata footer** — every response shows model, turns, cost, and duration

## Configuration

### Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SLACK_BOT_TOKEN` | Yes | -- | Bot user OAuth token (`xoxb-...`) |
| `SLACK_APP_TOKEN` | Yes (Socket Mode) | -- | App-level token (`xapp-...`) for Socket Mode |
| `SLACK_SIGNING_SECRET` | Yes (HTTP mode) | -- | Signing secret for request verification in HTTP mode |
| `SANDSTORM_SLACK_MODEL` | No | from config | Override the model for Slack responses |
| `SANDSTORM_SLACK_TIMEOUT` | No | `300` | Sandbox timeout in seconds |
| `ANTHROPIC_API_KEY` | Yes* | -- | Anthropic API key (or use OpenRouter) |
| `E2B_API_KEY` | Yes | -- | E2B sandbox API key |
| `OPENROUTER_API_KEY` | No | -- | OpenRouter key (if using OpenRouter) |

*Or equivalent provider key — see the main README for [provider setup](../README.md#providers).

### sandstorm.json

All `sandstorm.json` configuration applies to the Slack bot — system prompts, skills, subagents, MCP servers, allowed tools, and structured output all work the same way. The bot loads `sandstorm.json` from the working directory where `ds slack start` is run.

## Production (HTTP mode)

For production, use HTTP mode instead of Socket Mode. This runs a Starlette server that receives Slack events via HTTP:

```bash
ds slack start --http --port 3000
```

HTTP mode requires `SLACK_SIGNING_SECRET` (found in **Basic Information** on your Slack app page) instead of `SLACK_APP_TOKEN`. You'll also need to:

1. Set the **Request URL** in your Slack app's **Event Subscriptions** to `https://your-server.com/slack/events`
2. Set the **Interactivity Request URL** to the same URL
3. Deploy behind a reverse proxy (nginx, Caddy) with HTTPS

```bash
# Full production setup
export SLACK_BOT_TOKEN=xoxb-...
export SLACK_SIGNING_SECRET=...
export ANTHROPIC_API_KEY=sk-ant-...
export E2B_API_KEY=e2b_...

ds slack start --http --host 0.0.0.0 --port 3000
```

### CLI reference

```
ds slack setup                        # Interactive setup wizard
ds slack start                        # Socket Mode (development)
ds slack start --http                 # HTTP mode (production)
ds slack start --http --port 3000     # Custom port
ds slack start --http --host 0.0.0.0  # Custom bind address
```
