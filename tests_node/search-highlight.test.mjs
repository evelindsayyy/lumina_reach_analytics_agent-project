// Tests for lib/search-highlight.ts: which words of a query mark which words
// of a result, the way a results page marks what matched.

import { test } from "node:test";
import assert from "node:assert/strict";

import { highlightSegments, queryTerms } from "../lib/search-highlight.ts";

test("a query's terms are its meaningful words, lower case, once each", () => {
  assert.deepEqual(queryTerms("Who is overspending their BUDGET? budget!"), ["overspending", "budget"]);
  assert.deepEqual(queryTerms("Which device converts cheapest?"), ["device", "converts", "cheapest"]);
  assert.deepEqual(queryTerms(""), []);
});

test("short and filler words never mark anything", () => {
  assert.deepEqual(queryTerms("what does it do and how"), []);
});

test("a result is split into plain and matched pieces, text unchanged", () => {
  const segments = highlightSegments("Whether each campaign spends its budget well", ["budget"]);
  assert.deepEqual(segments, [
    { text: "Whether each campaign spends its ", match: false },
    { text: "budget", match: true },
    { text: " well", match: false },
  ]);
});

test("a word matches its own family: budget, budgets, budgeted", () => {
  const marked = highlightSegments("Budgets and the budgeted spend", ["budget"]).filter((s) => s.match);
  assert.deepEqual(
    marked.map((s) => s.text),
    ["Budgets", "budgeted"],
  );
});

test("no terms, or no match, is one plain piece", () => {
  assert.deepEqual(highlightSegments("Google vs Microsoft", []), [{ text: "Google vs Microsoft", match: false }]);
  assert.deepEqual(highlightSegments("Google vs Microsoft", ["tablet"]), [{ text: "Google vs Microsoft", match: false }]);
});
