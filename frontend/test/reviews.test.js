import { describe, test } from "node:test";
import assert from "node:assert/strict";

import {
  BODY_MAX,
  BODY_MIN,
  TITLE_MAX,
  ratingLabel,
  reviewDate,
  starBars,
  validateReview,
} from "../src/lib/reviews.js";

const GOOD = {
  rating: 4,
  title: "  Solid lamp  ",
  body: "  Bright enough for reading and the arm holds well.  ",
};

describe("validateReview", () => {
  test("accepts a complete review and trims the text", () => {
    const result = validateReview(GOOD);
    assert.equal(result.ok, true);
    assert.deepEqual(result.payload, {
      rating: 4,
      title: "Solid lamp",
      body: "Bright enough for reading and the arm holds well.",
    });
  });

  test("needs a whole-number rating from one to five stars", () => {
    assert.ok(validateReview({ ...GOOD, rating: 0 }).errors.rating);
    assert.ok(validateReview({ ...GOOD, rating: 6 }).errors.rating);
    assert.ok(validateReview({ ...GOOD, rating: 3.5 }).errors.rating);
  });

  test("checks the title after trimming it", () => {
    assert.ok(validateReview({ ...GOOD, title: "   " }).errors.title);
    assert.ok(validateReview({ ...GOOD, title: "x".repeat(TITLE_MAX + 1) }).errors.title);
    assert.equal(validateReview({ ...GOOD, title: "x".repeat(TITLE_MAX) }).ok, true);
  });

  test("checks the body length after trimming it", () => {
    assert.ok(validateReview({ ...GOOD, body: "too short" }).errors.body);
    assert.ok(validateReview({ ...GOOD, body: `${" ".repeat(50)}short` }).errors.body);
    assert.ok(validateReview({ ...GOOD, body: "x".repeat(BODY_MAX + 1) }).errors.body);
    assert.equal(validateReview({ ...GOOD, body: "x".repeat(BODY_MIN) }).ok, true);
  });
});

describe("ratingLabel", () => {
  test("says so before the first review", () => {
    assert.equal(ratingLabel(null, 0), "No reviews yet");
  });

  test("reads one review and many, to one decimal place", () => {
    assert.equal(ratingLabel("5.00", 1), "5.0 · 1 review");
    assert.equal(ratingLabel("4.67", 3), "4.7 · 3 reviews");
  });
});

describe("starBars", () => {
  test("lists five stars down to one, each with its share of the reviews", () => {
    const bars = starBars({ "5": 2, "4": 1, "3": 0, "2": 0, "1": 1 }, 4);
    assert.deepEqual(bars.map((bar) => bar.stars), [5, 4, 3, 2, 1]);
    assert.deepEqual(bars.map((bar) => bar.percent), [50, 25, 0, 0, 25]);
  });

  test("is all zero before any review", () => {
    assert.ok(starBars({}, 0).every((bar) => bar.count === 0 && bar.percent === 0));
  });
});

describe("reviewDate", () => {
  test("formats the day in London time", () => {
    assert.equal(reviewDate("2026-11-02T10:00:00Z"), "2 Nov 2026");
  });
});
