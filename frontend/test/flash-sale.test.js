import { describe, test } from "node:test";
import assert from "node:assert/strict";

import {
  countdown,
  discountPercent,
  minDefined,
  remainingLabel,
  remainingUnits,
  saleRequest,
  saleStatus,
  soldText,
  statusInTab,
} from "../src/lib/flashSale.js";

const NOW = new Date("2026-11-15T12:00:00Z");

function sale(overrides = {}) {
  return {
    id: "s1",
    name: "Weekend trainers",
    starts_at: "2026-11-15T09:00:00Z",
    ends_at: "2026-11-16T20:00:00Z",
    is_active: true,
    items: [{ id: "i1", quantity_cap: 200 }],
    ...overrides,
  };
}

describe("discounts", () => {
  test("the saving is the share of the regular price taken off, rounded", () => {
    assert.equal(discountPercent("40.00", "24.00"), 40);
    assert.equal(discountPercent("100.00", "80.00"), 20);
  });

  test("a sale price that is not below the regular price saves nothing", () => {
    assert.equal(discountPercent("40.00", "40.00"), 0);
    assert.equal(discountPercent("40.00", "45.00"), 0);
  });
});

describe("units left", () => {
  test("the cap less what has sold", () => {
    assert.equal(remainingUnits(200, 188), 12);
  });

  test("never goes below zero", () => {
    assert.equal(remainingUnits(5, 9), 0);
  });

  test("a missing sold count counts as none sold", () => {
    assert.equal(remainingUnits(200), 200);
  });

  test("the smaller of inventory and the sale cap is what the shopper can buy", () => {
    assert.equal(minDefined(undefined, 12), 12);
    assert.equal(minDefined(3, 12), 3);
    assert.equal(minDefined(undefined, undefined), undefined);
  });

  test("the label says how many are left, or that the price is sold out", () => {
    assert.equal(remainingLabel(12), "Only 12 left at this price");
    assert.equal(remainingLabel(0), "Sold out at this price");
    assert.equal(remainingLabel(undefined), null);
  });
});

describe("countdown", () => {
  test("shows hours, minutes and seconds for a sale ending today", () => {
    assert.equal(countdown((2 * 3600 + 14 * 60 + 37) * 1000), "02:14:37");
  });

  test("adds days for a longer sale", () => {
    assert.equal(countdown((2 * 86400 + 3 * 3600) * 1000), "2d 03:00:00");
  });

  test("an ended sale reads zero", () => {
    assert.equal(countdown(-5000), "00:00:00");
  });
});

describe("sale status", () => {
  test("a sale inside its window with stock left is live", () => {
    assert.equal(saleStatus(sale(), NOW, { i1: 84 }), "live");
  });

  test("a switched-off sale is off, even inside its window", () => {
    assert.equal(saleStatus(sale({ is_active: false }), NOW), "off");
  });

  test("a sale that starts later is scheduled", () => {
    assert.equal(saleStatus(sale({ starts_at: "2026-11-27T00:00:00Z" }), NOW), "scheduled");
  });

  test("a sale past its end is ended", () => {
    assert.equal(saleStatus(sale({ ends_at: "2026-11-14T20:00:00Z" }), NOW), "ended");
  });

  test("a sale whose capped items have all sold out is sold out", () => {
    assert.equal(saleStatus(sale(), NOW, { i1: 200 }), "sold_out");
  });

  test("a sale with any uncapped item is never sold out", () => {
    const mixed = sale({ items: [{ id: "i1", quantity_cap: 200 }, { id: "i2", quantity_cap: null }] });
    assert.equal(saleStatus(mixed, NOW, { i1: 200 }), "live");
  });

  test("sold-out, ended and switched-off sales sit under the Ended tab", () => {
    assert.equal(statusInTab("sold_out", "ended"), true);
    assert.equal(statusInTab("off", "ended"), true);
    assert.equal(statusInTab("live", "ended"), false);
    assert.equal(statusInTab("scheduled", ""), true);
  });

  test("the sold count adds up the capped items", () => {
    const two = sale({ items: [{ id: "i1", quantity_cap: 200 }, { id: "i2", quantity_cap: 50 }] });
    assert.equal(soldText(two, { i1: 84, i2: 6 }), "90 of 250");
    assert.equal(soldText(sale({ items: [{ id: "i1", quantity_cap: null }] })), "No cap");
  });
});

describe("the admin sale form", () => {
  test("becomes a request with ISO times and caps as numbers or null", () => {
    const request = saleRequest({
      name: "  Weekend trainers ",
      starts_at: "2026-11-15T09:00",
      ends_at: "2026-11-16T21:00",
      items: [
        { variant: "v1", sale_price: " 24.00 ", quantity_cap: "200" },
        { variant: "v2", sale_price: "30.00", quantity_cap: "" },
      ],
    });
    assert.equal(request.name, "Weekend trainers");
    assert.equal(request.starts_at, new Date("2026-11-15T09:00").toISOString());
    assert.deepEqual(request.items, [
      { variant: "v1", sale_price: "24.00", quantity_cap: 200 },
      { variant: "v2", sale_price: "30.00", quantity_cap: null },
    ]);
  });

  test("a blank or unreadable time is sent as null, so the API asks for it", () => {
    const request = saleRequest({ name: "A", starts_at: "", ends_at: "not a date", items: [] });
    assert.equal(request.starts_at, null);
    assert.equal(request.ends_at, null);
  });
});
