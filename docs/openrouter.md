# OpenRouter Integration

Sandstorm works with any model available on [OpenRouter](https://openrouter.ai) -- not just Claude. Run agents powered by GPT-4o, Qwen, Llama, DeepSeek, Gemini, Mistral, or any of 300+ models, all through the same API. OpenRouter exposes an Anthropic-compatible endpoint, so Sandstorm treats it as a drop-in replacement -- no code changes needed, just three env vars.

## Setup

Add three env vars to `.env`:

```bash
ANTHROPIC_BASE_URL=https://openrouter.ai/api
OPENROUTER_API_KEY=sk-or-...
ANTHROPIC_DEFAULT_SONNET_MODEL=anthropic/claude-sonnet-4  # or any OpenRouter model ID
```

That's it. The agent now routes through OpenRouter. Your existing `ANTHROPIC_API_KEY` can stay in `.env` -- Sandstorm automatically clears it in the sandbox when OpenRouter is active.

## Using Open-Source Models

Remap the SDK's model aliases to any OpenRouter model:

```bash
# Route "sonnet" to Qwen
ANTHROPIC_DEFAULT_SONNET_MODEL=qwen/qwen3-max-thinking

# Route "opus" to DeepSeek
ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek/deepseek-r1

# Route "haiku" to a fast, cheap model
ANTHROPIC_DEFAULT_HAIKU_MODEL=qwen/qwen3-30b-a3b
```

Then use the alias in your request or `sandstorm.json`:

```bash
curl -N -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Analyze this CSV and build a chart", "model": "sonnet"}'
```

The agent runs on Qwen, DeepSeek, or whatever you mapped -- with full tool use, file access, and streaming.

## Per-Request Keys

Pass `openrouter_api_key` in the request body for multi-tenant setups:

```bash
curl -N -X POST http://localhost:8000/query \
  -d '{"prompt": "...", "openrouter_api_key": "sk-or-...", "model": "sonnet"}'
```

## How It Works

The Claude Agent SDK supports custom API endpoints via `ANTHROPIC_BASE_URL`. OpenRouter exposes an Anthropic-compatible API, so the SDK sends requests to OpenRouter instead of Anthropic directly. OpenRouter then routes to whatever model you've configured. The `ANTHROPIC_DEFAULT_*_MODEL` env vars tell the SDK which model ID to send when you use aliases like `sonnet` or `opus`.

## Compatibility

Most models on OpenRouter support the core agent capabilities (tool use, streaming, multi-turn). Models with strong tool-use support (Claude, GPT-4o, Qwen, DeepSeek) work best. Smaller or older models may struggle with complex tool chains.

Browse available models at [openrouter.ai/models](https://openrouter.ai/models).
