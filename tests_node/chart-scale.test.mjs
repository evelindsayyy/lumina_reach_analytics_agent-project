// Tests for the chart geometry in components/chat/blocks/chart/scale.ts.
//
// The chart is drawn at the width it is shown at, so one SVG unit is one CSS
// pixel and the 11px labels stay 11px on a phone. These check the geometry a
// width produces, and the x-axis label thinning that has to follow it. Found in
// a recorded answer: 21 daily labels ("06-23" ...) overlapped into one band.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  CATEGORY_LABEL_SIZE,
  DEFAULT_WIDTH,
  MIN_WIDTH,
  buildYAxis,
  categoryCenter,
  categoryLabelStep,
  chartGeometry,
} from "../components/chat/blocks/chart/scale.ts";

const days = (n) => Array.from({ length: n }, (_, i) => `07-${String(i + 1).padStart(2, "0")}`);

test("the default geometry is the desktop one", () => {
  const g = chartGeometry();
  assert.equal(g.width, DEFAULT_WIDTH);
  assert.equal(g.height, 300);
  assert.equal(g.plotWidth, g.plotRight - g.plotLeft);
});

test("a phone-width chart is drawn at that width, a little shorter", () => {
  const g = chartGeometry(311);
  assert.equal(g.width, 311);
  assert.ok(g.height < 300 && g.height >= 200, `height ${g.height}`);
  assert.ok(g.plotWidth > 0 && g.plotRight <= g.width);
});

test("a width too small to read is held at the minimum", () => {
  assert.equal(chartGeometry(120).width, MIN_WIDTH);
  assert.equal(chartGeometry(Number.NaN).width, DEFAULT_WIDTH);
});

test("a phone's chart bubble (about 240px) is drawn at its own width", () => {
  assert.equal(chartGeometry(240).width, 240);
  assert.ok(MIN_WIDTH <= 220);
});

test("the left margin fits the longest y tick label, not a fixed width", () => {
  const short = chartGeometry(320, 2); // ticks like "60"
  const long = chartGeometry(320, 9); // ticks like "1,200,000"
  assert.ok(short.plotLeft < long.plotLeft);
  assert.ok(long.plotLeft >= 9 * CATEGORY_LABEL_SIZE * 0.6);
  assert.ok(short.plotWidth > long.plotWidth);
});

test("categories are centred inside the plot of the given geometry", () => {
  const g = chartGeometry(320);
  const first = categoryCenter(0, 4, g);
  const last = categoryCenter(3, 4, g);
  assert.ok(first > g.plotLeft && last < g.plotRight);
});

test("the y axis spans the plot of the given geometry and keeps zero", () => {
  const g = chartGeometry(320);
  const axis = buildYAxis([12, 48], g);
  assert.equal(axis.y(axis.max), g.plotTop);
  assert.equal(axis.y(axis.min), g.plotBottom);
  assert.ok(axis.ticks.includes(0));
});

test("labels that fit are all shown", () => {
  const { plotWidth } = chartGeometry();
  assert.equal(categoryLabelStep(["Mobile", "Desktop", "Tablet"], plotWidth), 1);
  assert.equal(
    categoryLabelStep(["Paid Search", "Display", "Paid Social", "Organic Search", "Email", "Direct"], plotWidth),
    1,
  );
});

test("21 daily labels are thinned until neighbours no longer touch, at any width", () => {
  for (const width of [640, 400, 311]) {
    const { plotWidth } = chartGeometry(width);
    const labels = days(21);
    const step = categoryLabelStep(labels, plotWidth);
    const apart = (plotWidth / labels.length) * step;
    assert.ok(apart >= 5 * CATEGORY_LABEL_SIZE * 0.6, `width ${width}: labels ${apart} apart`);
  }
});

test("a narrower chart shows fewer labels, never more", () => {
  const labels = days(21);
  assert.ok(categoryLabelStep(labels, chartGeometry(311).plotWidth) >= categoryLabelStep(labels, chartGeometry().plotWidth));
});

test("no categories is a step of one", () => {
  assert.equal(categoryLabelStep([], chartGeometry().plotWidth), 1);
});
