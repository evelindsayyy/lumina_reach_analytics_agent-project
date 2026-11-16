// Tests for lib/demo-answers.ts: which requests replay a recorded answer, and
// the stream that replays it.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  demoNote,
  demoStreamEvents,
  demoStreamResponse,
  findDemoAnswer,
  firstQuestionOf,
} from "../lib/demo-answers.ts";

const DEMOS = {
  recordedAt: "2026-11-16",
  model: "claude-acme",
  answers: [
    {
      title: "Top Widgets",
      question: "List the ten best-selling widgets.",
      reasoning: "Rank widgets by units sold.",
      answer: "| widget | units |\n|---|---|\n| A | 1,024 |",
      seconds: 18.4,
      inputTokens: 9000,
      outputTokens: 400,
    },
  ],
};

function request(...texts) {
  return JSON.stringify({
    id: "chat-1",
    trigger: "submit-message",
    messages: texts.map((text, i) => ({
      id: `m${i}`,
      role: i % 2 === 0 ? "user" : "assistant",
      parts: [{ type: "text", text }],
    })),
  });
}

/** The `data:` payloads of SSE event strings, `[DONE]` kept as a string. */
function payloads(events) {
  return events
    .map((e) => e.slice("data: ".length).trim())
    .map((data) => (data === "[DONE]" ? data : JSON.parse(data)));
}

test("the question of a new chat is its one user message", () => {
  assert.equal(firstQuestionOf(request("List the ten best-selling widgets.")), "List the ten best-selling widgets.");
  assert.equal(firstQuestionOf(request("Hi", "Hello", "List the ten best-selling widgets.")), null);
  assert.equal(firstQuestionOf("not json"), null);
  assert.equal(firstQuestionOf(JSON.stringify({ messages: "x" })), null);
});

test("only an example question, asked first, replays", () => {
  assert.equal(findDemoAnswer(request("List the ten best-selling widgets."), DEMOS)?.title, "Top Widgets");
  assert.equal(findDemoAnswer(request("  List the ten best-selling widgets. "), DEMOS)?.title, "Top Widgets");
  assert.equal(findDemoAnswer(request("List the ten worst widgets."), DEMOS), null);
  assert.equal(findDemoAnswer(request("Hi", "Hello", "List the ten best-selling widgets."), DEMOS), null);
});

test("the replay says it is a recording, from when, and how to ask live", () => {
  const note = demoNote(DEMOS, DEMOS.answers[0]);
  assert.match(note, /Recorded answer/);
  assert.match(note, /2026-11-16/);
  assert.match(note, /AgentCore/);
  assert.match(note, /own question/);
});

test("the replay is a complete UI message stream: reasoning, then the answer in pieces", () => {
  const events = payloads(demoStreamEvents(DEMOS.answers[0], DEMOS, 10));
  const types = events.map((e) => (typeof e === "string" ? e : e.type));
  assert.deepEqual(types.slice(0, 4), ["reasoning-start", "reasoning-delta", "reasoning-end", "text-start"]);
  assert.deepEqual(types.slice(-3), ["text-end", "finish", "[DONE]"]);
  const text = events.filter((e) => e.type === "text-delta").map((e) => e.delta);
  assert.ok(text.length > 2);
  assert.equal(text.join(""), demoNote(DEMOS, DEMOS.answers[0]) + DEMOS.answers[0].answer);
});

test("a recording without reasoning has no empty reasoning block", () => {
  const demo = { ...DEMOS.answers[0], reasoning: "" };
  const types = payloads(demoStreamEvents(demo, DEMOS)).map((e) => (typeof e === "string" ? e : e.type));
  assert.ok(!types.includes("reasoning-start"));
});

test("the response streams every event, in order", async () => {
  const events = demoStreamEvents(DEMOS.answers[0], DEMOS, 10);
  const response = demoStreamResponse(events, { "content-type": "text/event-stream" }, 0);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("content-type"), "text/event-stream");
  assert.equal(await response.text(), events.join(""));
});
