# @duvo/sandstorm-client

Thin TypeScript client for the [Sandstorm](https://github.com/tomascupr/sandstorm)
agent runtime, stream agent runs over SSE, list prior runs, check health.
Zero runtime dependencies (uses global `fetch`).

## Install

```bash
npm install @duvo/sandstorm-client
# or
pnpm add @duvo/sandstorm-client
```

Requires Node 18+ (or any runtime with a global `fetch`).

## Quick start

```ts
import { SandstormClient } from "@duvo/sandstorm-client";

const client = new SandstormClient({
  baseUrl: "http://localhost:8000",
  apiKey: process.env.SANDSTORM_API_KEY, // optional, only when server auth is on
});

for await (const event of client.query({
  prompt: "Summarize the changelog at https://github.com/vercel/next.js/releases",
  model: "sonnet",
})) {
  if (event.json && typeof event.json === "object") {
    const msg = event.json as { type?: string; message?: unknown };
    if (msg.type === "assistant") console.log(msg.message);
  }
}
```

## API

### `new SandstormClient(options)`

| Option    | Type                      | Required | Notes                                     |
| --------- | ------------------------- | -------- | ----------------------------------------- |
| `baseUrl` | `string`                  | yes      | e.g. `http://localhost:8000`              |
| `apiKey`  | `string`                  | no       | Sent as `Authorization: Bearer ...`       |
| `fetch`   | `typeof fetch`            | no       | Custom fetch impl (tests, custom agents)  |

### `client.query(request): AsyncIterable<SSEEvent>`

Streams the agent run. `SSEEvent.data` is the raw JSON line from the Agent
SDK runner; `SSEEvent.json` is the parsed object (or `null` for non-JSON
keepalives). Mirrors `POST /query`.

### `client.listRuns(limit?): Promise<Run[]>`

Returns the most recent runs, newest first. Mirrors `GET /runs`.

### `client.health(): Promise<HealthResponse>`

Mirrors `GET /health`.

## Types

All request and response types are re-exported from the entry point 
`QueryRequest`, `Run`, `SSEEvent`, `HealthResponse`, `ClientOptions`.

## Examples

See `examples/chat.ts` for a minimal CLI-style example.

## License

MIT
