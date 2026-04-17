/**
 * @duvo/sandstorm-client
 *
 * Minimal TypeScript client for Sandstorm — stream agent runs over SSE, manage
 * memory via slash-command-equivalent endpoints, replay past runs.
 *
 * Example:
 *   const client = new SandstormClient({ baseUrl: "http://localhost:8000" });
 *   for await (const event of client.query({ prompt: "say hello" })) {
 *     console.log(event.data);
 *   }
 */

import type {
  ClientOptions,
  HealthResponse,
  QueryRequest,
  Run,
  SSEEvent,
} from "./types.js";

export * from "./types.js";

export class SandstormClient {
  readonly baseUrl: string;
  private readonly apiKey?: string;
  private readonly fetchImpl: typeof globalThis.fetch;

  constructor(options: ClientOptions) {
    if (!options.baseUrl) {
      throw new Error("SandstormClient: baseUrl is required");
    }
    this.baseUrl = options.baseUrl.replace(/\/$/, "");
    this.apiKey = options.apiKey;
    this.fetchImpl = options.fetch ?? globalThis.fetch;
    if (!this.fetchImpl) {
      throw new Error(
        "SandstormClient: no fetch available — pass options.fetch or upgrade to Node 18+",
      );
    }
  }

  /** Stream an agent run as Server-Sent Events. */
  async *query(request: QueryRequest): AsyncIterable<SSEEvent> {
    const resp = await this.fetchImpl(`${this.baseUrl}/query`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        ...(this.apiKey ? { Authorization: `Bearer ${this.apiKey}` } : {}),
      },
      body: JSON.stringify(request),
    });
    if (!resp.ok) {
      const body = await resp.text().catch(() => "");
      throw new Error(`POST /query failed: ${resp.status} ${resp.statusText} — ${body}`);
    }
    if (!resp.body) {
      throw new Error("POST /query returned no body");
    }
    yield* parseSSEStream(resp.body);
  }

  async health(): Promise<HealthResponse> {
    const resp = await this.fetchImpl(`${this.baseUrl}/health`);
    if (!resp.ok) {
      throw new Error(`GET /health failed: ${resp.status} ${resp.statusText}`);
    }
    return (await resp.json()) as HealthResponse;
  }

  async listRuns(limit = 50): Promise<Run[]> {
    const resp = await this.fetchImpl(
      `${this.baseUrl}/runs?limit=${encodeURIComponent(limit)}`,
      {
        headers: this.apiKey ? { Authorization: `Bearer ${this.apiKey}` } : {},
      },
    );
    if (!resp.ok) {
      throw new Error(`GET /runs failed: ${resp.status} ${resp.statusText}`);
    }
    return (await resp.json()) as Run[];
  }
}

/** Parse an SSE response body into typed events. */
async function* parseSSEStream(body: ReadableStream<Uint8Array>): AsyncIterable<SSEEvent> {
  // Guard against a misbehaving server / proxy that strips the "\n\n" event
  // terminator; without a ceiling `buffer` would grow until the client OOMs.
  const MAX_BUFFER_BYTES = 16 * 1024 * 1024;
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      if (buffer.length > MAX_BUFFER_BYTES) {
        throw new Error(
          `Sandstorm SSE: event exceeds ${MAX_BUFFER_BYTES} bytes without a terminator`,
        );
      }
      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const rawEvent = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const parsed = parseSSEEvent(rawEvent);
        if (parsed) yield parsed;
        boundary = buffer.indexOf("\n\n");
      }
    }
  } finally {
    reader.releaseLock();
  }
}

function parseSSEEvent(raw: string): SSEEvent | null {
  const lines = raw.split(/\r?\n/);
  const dataLines: string[] = [];
  let event: string | undefined;
  for (const line of lines) {
    if (!line || line.startsWith(":")) continue; // comments / keepalives
    if (line.startsWith("data:")) {
      // Per SSE spec: strip a single leading space after the colon; multiple
      // data lines are joined with "\n" to reconstruct multi-line payloads.
      const raw = line.slice(5);
      dataLines.push(raw.startsWith(" ") ? raw.slice(1) : raw);
    } else if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    }
  }
  if (dataLines.length === 0) return null;
  const data = dataLines.join("\n");
  let json: unknown = null;
  try {
    json = JSON.parse(data);
  } catch {
    // non-JSON SSE payload: leave `json` null
  }
  return { data, json, event };
}
