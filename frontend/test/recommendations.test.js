import { describe, test } from "node:test";
import assert from "node:assert/strict";

import { SHOWN, visibleRecommendations } from "../src/lib/recommendations.js";

const item = (name, extra = {}) => ({
  product_id: `id-${name}`,
  name,
  slug: name.toLowerCase().replace(/ /g, "-"),
  image_url: "",
  ...extra,
});

describe("visibleRecommendations", () => {
  test("keeps the order the API gave and shows at most three", () => {
    const payload = { items: [item("Chair"), item("Desk Lamp"), item("Quiet Mug"), item("Rug")] };

    const shown = visibleRecommendations(payload);

    assert.equal(SHOWN, 3);
    assert.deepEqual(shown.map((entry) => entry.name), ["Chair", "Desk Lamp", "Quiet Mug"]);
  });

  test("drops an entry the block could not link to or show", () => {
    const payload = {
      items: [
        item("Chair"),
        { product_id: "id-no-name", slug: "no-name" },
        { product_id: "id-no-slug", name: "No slug" },
        null,
      ],
    };

    assert.deepEqual(visibleRecommendations(payload).map((entry) => entry.name), ["Chair"]);
  });

  test("gives an empty image address when the product has no picture", () => {
    const [entry] = visibleRecommendations({ items: [{ product_id: "id-a", name: "Lamp", slug: "lamp" }] });

    assert.equal(entry.image_url, "");
  });

  test("shows nothing for an empty or malformed answer", () => {
    assert.deepEqual(visibleRecommendations({ items: [] }), []);
    assert.deepEqual(visibleRecommendations({}), []);
    assert.deepEqual(visibleRecommendations(null), []);
    assert.deepEqual(visibleRecommendations({ items: "not a list" }), []);
  });
});
