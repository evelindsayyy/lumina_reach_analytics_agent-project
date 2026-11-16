// Tests for lib/next-questions.ts: what the chat offers to ask after an answer.

import { test } from "node:test";
import assert from "node:assert/strict";

import { nextQuestions } from "../lib/next-questions.ts";

const EXAMPLES = [
  { render: "free", title: "Intro", label: "What can you do?", action: "q-intro" },
  { render: "chart", title: "Gap", label: "What does last-click hide?", action: "q-gap" },
  { render: "flowchart", title: "Structure", label: "How is it organized?", action: "q-structure" },
  { render: "table", title: "Pacing", label: "Who overspends?", action: "q-pacing" },
  { render: "free", title: "Engine", label: "Move budget to Microsoft?", action: "q-engine" },
  { render: "chart", title: "Trend", label: "Is CPA improving?", action: "q-trend" },
];

const titles = (picked) => picked.map((p) => p.title);

test("after an example, the next ones in order, one of each kind where possible", () => {
  assert.deepEqual(titles(nextQuestions(EXAMPLES, ["q-gap"])), ["Structure", "Pacing", "Engine"]);
});

test("questions already asked in this chat are never offered again", () => {
  const picked = titles(nextQuestions(EXAMPLES, ["q-gap", "q-structure", "q-pacing"]));
  assert.deepEqual(picked, ["Engine", "Trend", "Intro"]);
});

test("after a typed question, the examples from the start", () => {
  assert.deepEqual(titles(nextQuestions(EXAMPLES, ["How many keywords are there?"])), ["Intro", "Gap", "Structure"]);
});

test("kinds are spread before they repeat", () => {
  // after Structure: Pacing(table), Engine(free), Trend(chart) beat Intro(free) and Gap(chart)
  assert.deepEqual(titles(nextQuestions(EXAMPLES, ["q-structure"])), ["Pacing", "Engine", "Trend"]);
});

test("asked text matches with surrounding space trimmed", () => {
  assert.ok(!titles(nextQuestions(EXAMPLES, ["  q-gap \n"])).includes("Gap"));
});

test("fewer are offered when few are left, none when all were asked", () => {
  const all = EXAMPLES.map((e) => e.action);
  assert.deepEqual(titles(nextQuestions(EXAMPLES, all.slice(0, 5))), ["Trend"]);
  assert.deepEqual(nextQuestions(EXAMPLES, all), []);
});

test("the count is a ceiling", () => {
  assert.equal(nextQuestions(EXAMPLES, ["q-gap"], 2).length, 2);
});
