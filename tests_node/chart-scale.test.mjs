// Tests for the x-axis label thinning in components/chat/blocks/chart/scale.ts.
// Found in a recorded answer: 21 daily labels ("06-23" ...) overlapped into
// one unreadable band, at every screen width (the SVG scales as a whole).

import { test } from "node:test";
import assert from "node:assert/strict";

import { categoryLabelStep, plotWidth } from "../components/chat/blocks/chart/scale.ts";

const days = (n) => Array.from({ length: n }, (_, i) => `07-${String(i + 1).padStart(2, "0")}`);

test("labels that fit are all shown", () => {
  assert.equal(categoryLabelStep(["Mobile", "Desktop", "Tablet"]), 1);
  assert.equal(categoryLabelStep(["Paid Search", "Display", "Paid Social", "Organic Search", "Email", "Direct"]), 1);
});

test("21 daily labels are thinned until neighbours no longer touch", () => {
  const labels = days(21);
  const step = categoryLabelStep(labels);
  assert.ok(step > 1);
  const slot = plotWidth / labels.length;
  const labelWidth = 5 * 11 * 0.6;
  assert.ok(slot * step >= labelWidth, `shown labels are ${slot * step} apart, need ${labelWidth}`);
});

test("the step grows with the number of categories, up to the cap", () => {
  assert.ok(categoryLabelStep(days(24)) >= categoryLabelStep(days(12)));
});

test("no categories is a step of one", () => {
  assert.equal(categoryLabelStep([]), 1);
});
