import { describe, test } from "node:test";
import assert from "node:assert/strict";

import {
  couponRequest,
  couponStatus,
  couponStatusLabel,
  discountLabel,
  normalizeCode,
  statusInTab,
  usageText,
  validityText,
} from "../src/lib/coupon.js";

const NOW = new Date("2026-11-15T12:00:00Z");

// A coupon as the API returns it, with the defaults a fresh code has.
function coupon(overrides = {}) {
  return {
    code: "WELCOME10",
    kind: "percent",
    value: "10.00",
    min_subtotal: "0.00",
    starts_at: null,
    ends_at: null,
    usage_limit: null,
    per_customer_limit: 1,
    is_active: true,
    used_count: 0,
    ...overrides,
  };
}

describe("codes", () => {
  test("are trimmed and put in capitals", () => {
    assert.equal(normalizeCode("  welcome10 "), "WELCOME10");
  });

  test("a missing code becomes an empty string", () => {
    assert.equal(normalizeCode(undefined), "");
  });
});

describe("discount labels", () => {
  test("a percentage reads as a percentage off", () => {
    assert.equal(discountLabel(coupon({ kind: "percent", value: "10.00" })), "10% off");
  });

  test("a fixed amount reads in pounds", () => {
    assert.equal(discountLabel(coupon({ kind: "fixed", value: "5" })), "£5.00 off");
  });
});

describe("status", () => {
  test("a code inside its dates with uses to spare is active", () => {
    assert.equal(couponStatus(coupon(), NOW), "active");
  });

  test("a switched-off code is off, even inside its dates", () => {
    assert.equal(couponStatus(coupon({ is_active: false }), NOW), "off");
  });

  test("a code that starts later is scheduled", () => {
    assert.equal(couponStatus(coupon({ starts_at: "2026-11-25T12:00:00Z" }), NOW), "scheduled");
  });

  test("a code past its end date has expired", () => {
    assert.equal(couponStatus(coupon({ ends_at: "2026-08-31T12:00:00Z" }), NOW), "expired");
  });

  test("a code that has reached its total uses is used up", () => {
    assert.equal(couponStatus(coupon({ usage_limit: 200, used_count: 200 }), NOW), "used_up");
  });

  test("expiry takes precedence over running out", () => {
    const expired = coupon({ ends_at: "2026-08-31T12:00:00Z", usage_limit: 1, used_count: 1 });
    assert.equal(couponStatus(expired, NOW), "expired");
  });

  test("labels read in plain words", () => {
    assert.equal(couponStatusLabel("used_up"), "Used up");
    assert.equal(couponStatusLabel("off"), "Switched off");
  });

  test("the Ended tab holds expired, used up and switched-off codes, and All holds everything", () => {
    assert.equal(statusInTab("expired", "ended"), true);
    assert.equal(statusInTab("used_up", "ended"), true);
    assert.equal(statusInTab("off", "ended"), true);
    assert.equal(statusInTab("active", "ended"), false);
    assert.equal(statusInTab("scheduled", ""), true);
  });
});

describe("the admin list text", () => {
  test("validity says when a code starts or ends, or that it has no end", () => {
    assert.equal(validityText(coupon({ starts_at: "2026-11-25T12:00:00Z" }), NOW), "Starts 25 Nov 2026");
    assert.equal(validityText(coupon({ ends_at: "2026-12-31T12:00:00Z" }), NOW), "Ends 31 Dec 2026");
    assert.equal(validityText(coupon({ ends_at: "2026-08-31T12:00:00Z" }), NOW), "Ended 31 Aug 2026");
    assert.equal(validityText(coupon(), NOW), "No end date");
  });

  test("usage shows the total limit and the per-customer limit", () => {
    assert.equal(usageText(coupon({ used_count: 84, usage_limit: 200 })), "84 of 200 · 1 per customer");
    assert.equal(usageText(coupon({ used_count: 0, usage_limit: null, per_customer_limit: null })), "0");
  });
});

describe("the admin form", () => {
  test("becomes a request with the code in capitals and empty optional fields left out", () => {
    const request = couponRequest({
      code: " welcome10 ",
      kind: "percent",
      value: "10",
      min_subtotal: "20",
      starts_at: "",
      ends_at: "",
      usage_limit: "",
      per_customer_limit: "1",
    });
    assert.deepEqual(request, {
      code: "WELCOME10",
      kind: "percent",
      value: "10",
      min_subtotal: "20",
      starts_at: null,
      ends_at: null,
      usage_limit: null,
      per_customer_limit: 1,
    });
  });

  test("a blank minimum basket is sent as zero", () => {
    assert.equal(couponRequest({ code: "A", kind: "fixed", value: "5", min_subtotal: "" }).min_subtotal, "0.00");
  });

  test("dates from the form are sent as ISO times", () => {
    const request = couponRequest({ code: "A", kind: "fixed", value: "5", ends_at: "2026-12-31T23:59" });
    assert.equal(request.ends_at, new Date("2026-12-31T23:59").toISOString());
  });

  test("the total limit becomes a number when one is given", () => {
    assert.equal(couponRequest({ code: "A", kind: "fixed", value: "5", usage_limit: "200" }).usage_limit, 200);
  });
});
