// Tests for lib/agent-proxy.ts, run by Node's own test runner. Node 24 strips
// the TypeScript types itself, so the module is imported as it ships.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  LOCAL_AGENT_RUNTIME_URL,
  RUNTIME_FAILED_MESSAGE,
  RUNTIME_UNREACHABLE_MESSAGE,
  SSE_HEADERS,
  agentRuntimeUrl,
  proxyChat,
  textStreamBody,
} from "../lib/agent-proxy.ts";

/** The `data:` payloads of an SSE body, `[DONE]` kept as a string. */
function events(body) {
  return body
    .split("\n\n")
    .filter((chunk) => chunk.startsWith("data: "))
    .map((chunk) => chunk.slice("data: ".length))
    .map((data) => (data === "[DONE]" ? data : JSON.parse(data)));
}

const CHAT = JSON.stringify({ id: "c1", messages: [] });

test("the runtime URL is AGENT_RUNTIME_URL, else the local runtime", () => {
  assert.equal(agentRuntimeUrl({}), LOCAL_AGENT_RUNTIME_URL);
  assert.equal(agentRuntimeUrl({ AGENT_RUNTIME_URL: "" }), LOCAL_AGENT_RUNTIME_URL);
  assert.equal(agentRuntimeUrl({ AGENT_RUNTIME_URL: "https://x/invocations" }), "https://x/invocations");
});

test("a text stream is a complete AI SDK v5 message", () => {
  const stream = events(textStreamBody("hello"));
  assert.deepEqual(
    stream.map((e) => (typeof e === "string" ? e : e.type)),
    ["text-start", "text-delta", "text-end", "finish", "[DONE]"],
  );
  assert.equal(stream[1].delta, "hello");
});

test("the request body and headers reach the runtime untouched", async () => {
  let seen;
  const fetchImpl = async (url, init) => {
    seen = { url, init };
    return new Response("data: {}\n\n", { status: 200 });
  };
  await proxyChat(CHAT, { url: "http://agent/invocations", headers: { authorization: "Bearer t" }, fetchImpl });
  assert.equal(seen.url, "http://agent/invocations");
  assert.equal(seen.init.method, "POST");
  assert.equal(seen.init.body, CHAT);
  assert.equal(seen.init.headers["content-type"], "application/json");
  assert.equal(seen.init.headers.authorization, "Bearer t");
});

test("the runtime's stream is passed through with the protocol headers", async () => {
  const upstreamBody = textStreamBody("from the agent", "a1");
  const fetchImpl = async () => new Response(upstreamBody, { status: 200 });
  const response = await proxyChat(CHAT, { url: "http://agent", fetchImpl });
  assert.equal(response.status, 200);
  for (const [key, value] of Object.entries(SSE_HEADERS)) {
    assert.equal(response.headers.get(key), value);
  }
  assert.equal(await response.text(), upstreamBody);
});

test("an unreachable runtime becomes a readable answer, not a 500", async () => {
  const fetchImpl = async () => {
    throw new TypeError("fetch failed");
  };
  const response = await proxyChat(CHAT, { url: "http://agent", fetchImpl });
  assert.equal(response.status, 200);
  assert.equal(events(await response.text())[1].delta, RUNTIME_UNREACHABLE_MESSAGE);
});

test("an error status from the runtime becomes a readable answer", async () => {
  const fetchImpl = async () => new Response("{\"detail\":\"bad\"}", { status: 400 });
  const response = await proxyChat(CHAT, { url: "http://agent", fetchImpl });
  assert.equal(events(await response.text())[1].delta, RUNTIME_FAILED_MESSAGE);
});
