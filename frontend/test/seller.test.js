import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  adminActions,
  canChangeProducts,
  confirmSuspend,
  sellersQuery,
  shopStatusLabel,
  shopStatusNote,
} from "../src/lib/seller.js";

describe("shop status copy", () => {
  it("gives every status a label and a note for the seller", () => {
    assert.equal(shopStatusLabel("pending"), "Waiting for approval");
    assert.equal(shopStatusLabel("approved"), "Approved");
    assert.equal(shopStatusLabel("suspended"), "Suspended");
    assert.match(shopStatusNote("suspended"), /can still read them/);
  });

  it("falls back to the raw status for anything unknown", () => {
    assert.equal(shopStatusLabel("archived"), "archived");
    assert.equal(shopStatusNote("archived"), "");
  });
});

describe("product changes", () => {
  it("only an approved shop can change its products", () => {
    assert.equal(canChangeProducts("approved"), true);
    assert.equal(canChangeProducts("pending"), false);
    assert.equal(canChangeProducts("suspended"), false);
    assert.equal(canChangeProducts(undefined), false);
  });
});

describe("admin actions", () => {
  it("approves a pending shop", () => {
    assert.deepEqual(adminActions("pending"), [{ action: "approve", label: "Approve" }]);
  });

  it("suspends an approved shop", () => {
    assert.deepEqual(adminActions("approved"), [{ action: "suspend", label: "Suspend" }]);
  });

  it("reinstates a suspended shop through approve", () => {
    assert.deepEqual(adminActions("suspended"), [{ action: "approve", label: "Reinstate" }]);
  });

  it("offers nothing for an unknown status", () => {
    assert.deepEqual(adminActions("archived"), []);
  });
});

describe("admin list", () => {
  it("lists every shop with no filter", () => {
    assert.equal(sellersQuery(""), "/api/v1/admin/sellers/");
  });

  it("filters by status, encoding the value", () => {
    assert.equal(sellersQuery("pending"), "/api/v1/admin/sellers/?status=pending");
  });

  it("names the shop in the suspend confirmation", () => {
    assert.match(confirmSuspend("Oak & Co"), /^Suspend “Oak & Co”\?/);
  });
});
