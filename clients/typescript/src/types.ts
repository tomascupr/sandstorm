/** Shapes mirror the Python QueryRequest / Run / SSE events. See
 *  src/sandstorm/models.py and src/sandstorm/store.py in the main repo. */

export interface QueryRequest {
  prompt: string;
  model?: string | null;
  max_turns?: number | null;
  timeout?: number | null;
  files?: Record<string, string> | null;
  anthropic_api_key?: string | null;
  e2b_api_key?: string | null;
  openrouter_api_key?: string | null;
  allowed_tools?: string[] | null;
  allowed_agents?: string[] | null;
  allowed_skills?: string[] | null;
  allowed_mcp_servers?: string[] | null;
  extra_agents?: Record<string, unknown> | null;
  extra_skills?: Record<string, string> | null;
  team_id?: string | null;
  user_id?: string | null;
  remember?: string | null;
  resume?: string | null;
  fork_session?: boolean | null;
  max_budget_usd?: number | null;
  output_format?: Record<string, unknown> | null;
}

export interface Run {
  id: string;
  prompt: string;
  model: string | null;
  status: "running" | "completed" | "error";
  started_at: string;
  cost_usd: number | null;
  num_turns: number | null;
  duration_secs: number | null;
  error: string | null;
  files_count: number;
  feedback: string | null;
  feedback_user: string | null;
  raw_prompt: string;
  agent_session_id: string | null;
  sandbox_id: string | null;
  team_id: string | null;
  user_id: string | null;
  channel_id: string | null;
  thread_ts: string | null;
  config_snapshot: Record<string, unknown> | null;
}

/** SSE events emitted by the /query stream. Each `data` field is one JSON line
 *  from the Agent SDK runner — opaque to the client library; users parse the
 *  inner JSON themselves. */
export interface SSEEvent {
  /** Parsed from `data:` — the raw JSON string from the runner. */
  data: string;
  /** Parsed JSON when `data` is valid JSON; null otherwise. Convenience field. */
  json: unknown | null;
  /** Event type (only set on named SSE events). */
  event?: string;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  version: string;
  checks?: Record<string, boolean>;
}

export interface ClientOptions {
  baseUrl: string;
  /** API token if the server has SANDSTORM_API_KEY configured. */
  apiKey?: string;
  /** Custom fetch implementation. Defaults to globalThis.fetch (Node 18+). */
  fetch?: typeof globalThis.fetch;
}
