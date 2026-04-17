# Multi-LLM: any provider the Agent SDK supports

Sandstorm is provider-agnostic. The `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN`
plumbing that the Agent SDK exposes means any OpenAI-compatible endpoint works.
This page shows the common configurations.

Running `ds doctor` will probe whichever provider you've configured.

## OpenRouter (GPT-5, Gemini, DeepSeek, Qwen, Kimi, Grok, etc.)

OpenRouter proxies hundreds of models behind one OpenAI-compatible endpoint.

`.env`:

```bash
OPENROUTER_API_KEY=sk-or-v1-...
# Sandstorm maps OPENROUTER_API_KEY → ANTHROPIC_AUTH_TOKEN inside the sandbox
# and sets ANTHROPIC_BASE_URL to https://openrouter.ai/api/v1 automatically.
```

`sandstorm.json`:

```json
{
  "model": "openai/gpt-5",
  "system_prompt": "You are a helpful assistant."
}
```

Or override per-request via `ds --model openai/gpt-5 "..."`. The full OpenRouter
model list is at <https://openrouter.ai/models>.

Common model strings:

- `openai/gpt-5`, `openai/gpt-5-mini`
- `google/gemini-2.5-pro`, `google/gemini-2.5-flash`
- `deepseek/deepseek-v3`
- `qwen/qwen-3-coder`
- `anthropic/claude-sonnet-4-20250514` (via OpenRouter, useful if you want to
  consolidate billing; Sandstorm uses direct Anthropic by default when you set
  `ANTHROPIC_API_KEY`).

See [docs/openrouter.md](openrouter.md) for OpenRouter-specific quirks.

## Google Vertex AI

For Claude models on GCP:

```bash
CLAUDE_CODE_USE_VERTEX=1
CLOUD_ML_REGION=us-central1
ANTHROPIC_VERTEX_PROJECT_ID=your-gcp-project
GOOGLE_APPLICATION_CREDENTIALS=/abs/path/to/service-account.json
```

The credentials file is uploaded into the sandbox at run time. Sandstorm reads
it eagerly (TOCTOU-safe) and puts it at `/home/user/.config/gcloud/service_account.json`.

## AWS Bedrock

```bash
CLAUDE_CODE_USE_BEDROCK=1
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
# AWS_SESSION_TOKEN=...   # if using STS temporary creds
```

## Microsoft Azure Foundry

```bash
CLAUDE_CODE_USE_FOUNDRY=1
AZURE_FOUNDRY_RESOURCE=your-resource
AZURE_API_KEY=...
```

## Self-hosted / Ollama / vLLM / custom OpenAI-compatible endpoints

Anything that speaks OpenAI's chat completions API works via the custom
base URL pattern:

```bash
ANTHROPIC_BASE_URL=https://your-endpoint.example.com/v1
ANTHROPIC_AUTH_TOKEN=optional-key-if-required
```

Then set a model string the endpoint understands:

```json
{ "model": "llama-3.3-70b-instruct" }
```

For Ollama specifically:

```bash
ANTHROPIC_BASE_URL=http://host.docker.internal:11434/v1
ANTHROPIC_AUTH_TOKEN=ollama
```

When `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN` are both set, Sandstorm
deliberately clears `ANTHROPIC_API_KEY` inside the sandbox, otherwise the
Agent SDK validates model names against Anthropic's API and rejects anything
non-Claude.

## Model aliases

If you want `sonnet` / `opus` / `haiku` in config to resolve to provider-specific
model IDs (e.g. Vertex model names), set:

```bash
ANTHROPIC_DEFAULT_SONNET_MODEL=claude-sonnet-4@20250514
ANTHROPIC_DEFAULT_OPUS_MODEL=claude-opus-4@7
ANTHROPIC_DEFAULT_HAIKU_MODEL=claude-haiku-4-5@20251001
```

These map the aliases the SDK uses onto whatever ID the provider expects.

## Sanity-checking a provider swap

After changing provider env vars, always:

1. `ds doctor`: confirms creds are live.
2. `ds "say hello"`: one-turn probe to verify the model answers.
3. Watch traces in your observability backend (see [observability.md](observability.md)).

If a model string is wrong, the agent returns an error event rather than failing
silently, so `ds doctor` + one echo prompt catches 95% of provider-swap bugs.
