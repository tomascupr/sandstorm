# Observability

Sandstorm exports OpenTelemetry spans for every `/query` request, every
SDK message, every tool call, and every cost event. Point any OTel-compatible
backend at it and you get a full trace tree of what the agent did, what
it cost, and how long each step took.

Nothing is tied to Anthropic's console. Your runtime traces stay in your
infra.

## Enable

```bash
pip install "duvo-sandstorm[telemetry]"
```

Set the env vars in `.env` (or your container's env):

```bash
SANDSTORM_TELEMETRY=1
OTEL_EXPORTER_OTLP_ENDPOINT=https://your-collector.example.com
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic%20XXX
OTEL_SERVICE_NAME=sandstorm
```

Sandstorm uses OTLP/HTTP by default. Switch to OTLP/gRPC by setting
`OTEL_EXPORTER_OTLP_PROTOCOL=grpc`.

## Langfuse

[Langfuse](https://langfuse.com) is the most popular OSS option for agent
observability. Point sandstorm at its OTel ingest endpoint:

```bash
# Hosted
OTEL_EXPORTER_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic%20$(echo -n pk-...:sk-... | base64)
OTEL_SERVICE_NAME=sandstorm
SANDSTORM_TELEMETRY=1
```

Or run Langfuse locally alongside sandstorm:

```bash
docker compose -f deploy/docker-compose.langfuse.yml up
```

Open <http://localhost:3000> to see traces, costs, and the full span tree
for each run.

## Phoenix / Arize

[Phoenix](https://arize.com/docs/phoenix) is Arize's OSS agent tracing tool.
Same pattern. Phoenix speaks OTLP:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:6006/v1/traces
OTEL_SERVICE_NAME=sandstorm
SANDSTORM_TELEMETRY=1
```

Run Phoenix with `pip install arize-phoenix && phoenix serve`.

## Langsmith

[LangSmith](https://smith.langchain.com) also accepts OTLP traces:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=https://api.smith.langchain.com/otel
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer%20<LANGSMITH_API_KEY>,Langsmith-Project=sandstorm
OTEL_SERVICE_NAME=sandstorm
SANDSTORM_TELEMETRY=1
```

## What gets traced

Each `/query` request produces one root span (`query`) with child spans for:

- `sandbox.create`: E2B cold-start latency
- `agent.execute`: runner.mjs lifetime, model, has_skills
- `webhook.e2b`: incoming E2B lifecycle events

Counters exported alongside:

- `sandstorm.requests_total{model,status}`
- `sandstorm.request_duration_seconds{model}`
- `sandstorm.errors_total{error_type}`
- `sandstorm.sandbox_creation_seconds{template}`
- `sandstorm.sandboxes_active`
- `sandstorm.queue_drops_total`
- `sandstorm.webhook_events_total{event_type}`

## Verifying

After configuring, run:

```bash
ds doctor
```

The doctor output includes an `OTel endpoint` row that probes reachability.

Then send a test query:

```bash
ds "say hello"
```

A span named `query` should appear in your backend within a few seconds.
If nothing shows up, check `OTEL_EXPORTER_OTLP_ENDPOINT` and that your
`SANDSTORM_TELEMETRY=1` is set in the same environment sandstorm is running in.
