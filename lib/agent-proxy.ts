// The web tier's whole backend: forward the chat request to the agent runtime
// and stream its answer back untouched.
//
// The agent runtime (agent_app/runtimes/analytics_agent.py) already speaks the
// AI SDK v5 UI message stream, so nothing here parses or rewrites the body.
// What this file owns is the failure path: when the runtime cannot be reached
// or answers with an error status, the reader gets a sentence in the chat
// instead of a broken turn.
//
// No imports on purpose, so `node --test` runs it directly (tests_node/).

/** Headers the AI SDK needs to read the body as a v5 UI message stream. */
export const SSE_HEADERS: Readonly<Record<string, string>> = {
  "content-type": "text/event-stream",
  "x-vercel-ai-ui-message-stream": "v1",
  "cache-control": "no-cache",
  connection: "keep-alive",
};

/** Where the agent runtime listens under `mise run dev`. */
export const LOCAL_AGENT_RUNTIME_URL = "http://127.0.0.1:8080/invocations";

export const RUNTIME_UNREACHABLE_MESSAGE =
  "I could not reach the agent service, so I could not answer. " +
  "If you are running this locally, start it with `mise run dev`.";

export const RUNTIME_FAILED_MESSAGE =
  "The agent service failed on this request, so I could not answer. " +
  "Please try again; if it keeps failing, its log has the details.";

export const SIGN_IN_REQUIRED_MESSAGE =
  "Please sign in to ask your own question: use **Sign in** at the top right. " +
  "Each account gets a few live questions a month. Without signing in, start a " +
  "new chat and pick one of the example questions: each replays an answer " +
  "recorded from the live agent.";

export const SESSION_EXPIRED_MESSAGE =
  "Your session has expired. Please sign in again (top right) and resend your question.";

/** The agent runtime's invocation URL: `AGENT_RUNTIME_URL`, else the local one. */
export function agentRuntimeUrl(
  env: Readonly<Record<string, string | undefined>>,
): string {
  return env.AGENT_RUNTIME_URL || LOCAL_AGENT_RUNTIME_URL;
}

function sseEvent(payload: unknown): string {
  return `data: ${JSON.stringify(payload)}\n\n`;
}

/** A complete UI message stream carrying one text answer. */
export function textStreamBody(text: string, id = "proxy-message"): string {
  return [
    sseEvent({ type: "text-start", id }),
    sseEvent({ type: "text-delta", id, delta: text }),
    sseEvent({ type: "text-end", id }),
    sseEvent({ type: "finish", finishReason: "stop" }),
    "data: [DONE]\n\n",
  ].join("");
}

export function textStreamResponse(text: string): Response {
  return new Response(textStreamBody(text), { status: 200, headers: SSE_HEADERS });
}

export interface ProxyOptions {
  url: string;
  /** Extra request headers, such as the user's token once the runtime checks one. */
  headers?: Readonly<Record<string, string>>;
  /** Aborts the upstream call when the browser goes away. */
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
}

/** The `id` of an AI SDK chat request (the conversation's id), or "" if it has none. */
export function chatIdOf(body: string): string {
  try {
    const id = (JSON.parse(body) as { id?: unknown }).id;
    return typeof id === "string" ? id : "";
  } catch {
    return "";
  }
}

/**
 * POST `body` (the AI SDK request JSON, as received) to the agent runtime and
 * return its stream. Never throws: every failure becomes a readable answer.
 */
export async function proxyChat(body: string, options: ProxyOptions): Promise<Response> {
  const fetchImpl = options.fetchImpl ?? fetch;
  let upstream: Response;
  try {
    upstream = await fetchImpl(options.url, {
      method: "POST",
      headers: { "content-type": "application/json", ...options.headers },
      body,
      signal: options.signal,
    });
  } catch (error: unknown) {
    console.error("[agent-proxy] agent runtime unreachable", error);
    return textStreamResponse(RUNTIME_UNREACHABLE_MESSAGE);
  }

  if (upstream.status === 401 || upstream.status === 403) {
    // the runtime's JWT authorizer refused the token
    console.error(`[agent-proxy] agent runtime refused the token: HTTP ${upstream.status}`);
    return textStreamResponse(SESSION_EXPIRED_MESSAGE);
  }
  if (!upstream.ok || !upstream.body) {
    console.error(`[agent-proxy] agent runtime answered HTTP ${upstream.status}`);
    return textStreamResponse(RUNTIME_FAILED_MESSAGE);
  }

  return new Response(upstream.body, { status: 200, headers: SSE_HEADERS });
}
