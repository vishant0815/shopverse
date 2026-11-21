import { describe, test } from "node:test";
import assert from "node:assert/strict";

import { barHeights, conversionLabel, dayLabel } from "../src/lib/analytics.js";

describe("conversionLabel", () => {
  test("rounds the share of views that led to a basket to a whole percentage", () => {
    assert.equal(conversionLabel(0.333), "33%");
    assert.equal(conversionLabel(0.5), "50%");
    assert.equal(conversionLabel(0), "0%");
  });

  test("says so plainly when nothing was viewed", () => {
    assert.equal(conversionLabel(null), "No views yet");
    assert.equal(conversionLabel(undefined), "No views yet");
  });
});

describe("barHeights", () => {
  test("scales every bar against the largest, which fills the chart", () => {
    assert.deepEqual(barHeights([0, 5, 10]), [0, 50, 100]);
  });

  test("keeps every bar empty when nothing was sold", () => {
    assert.deepEqual(barHeights([0, 0, 0]), [0, 0, 0]);
  });

  test("gives no bars for no days", () => {
    assert.deepEqual(barHeights([]), []);
  });
});

describe("dayLabel", () => {
  test("names the weekday, day and month of a UTC day", () => {
    assert.equal(dayLabel("2026-11-18"), "Wed 18 Nov");
  });

  test("does not move the day across a time zone boundary", () => {
    assert.equal(dayLabel("2026-01-01"), "Thu 1 Jan");
  });
});
