import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  buildHref,
  normalizeSearch,
  nextIndex,
  parseSearchParams,
  PAGE_SIZE,
  shouldSuggest,
  suggestUrl,
  toProductsQuery,
  toSearchQuery,
} from "../src/lib/search-model.js";

describe("parseSearchParams", () => {
  it("defaults to newest when there is no search, and relevance when there is one", () => {
    assert.equal(parseSearchParams({}).sort, "newest");
    assert.equal(parseSearchParams({ search: "desk" }).sort, "relevance");
  });

  it("keeps a valid sort and ignores an unknown one", () => {
    assert.equal(parseSearchParams({ sort: "price_asc" }).sort, "price_asc");
    assert.equal(parseSearchParams({ search: "desk", sort: "name" }).sort, "relevance");
  });

  it("drops prices that are not numbers in range, and swaps an inverted range", () => {
    assert.equal(parseSearchParams({ min_price: "abc" }).min_price, "");
    assert.equal(parseSearchParams({ max_price: "2000000" }).max_price, "");
    assert.equal(parseSearchParams({ min_price: "50", max_price: "10" }).min_price, "10");
    assert.equal(parseSearchParams({ min_price: "50", max_price: "10" }).max_price, "50");
  });

  it("reads pages safely", () => {
    assert.equal(parseSearchParams({ page: "abc" }).page, 1);
    assert.equal(parseSearchParams({ page: "0" }).page, 1);
    assert.equal(parseSearchParams({ page: "999" }).page, 200);
    assert.equal(parseSearchParams({ page: "3" }).page, 3);
  });

  it("uses the first value of a repeated key and trims text", () => {
    assert.equal(parseSearchParams({ search: ["  desk ", "lamp"] }).search, "desk");
    assert.equal(parseSearchParams({ brand: "x".repeat(300) }).brand.length, 100);
  });

  it("only treats on_sale as on when it is exactly true", () => {
    assert.equal(parseSearchParams({ on_sale: "true" }).on_sale, "true");
    assert.equal(parseSearchParams({ on_sale: "yes" }).on_sale, "");
  });
});

describe("API parameters", () => {
  it("maps the page to search parameters", () => {
    const query = toSearchQuery(parseSearchParams({ search: "desk", colour: "Oak", page: "2" }));

    assert.equal(query.q, "desk");
    assert.equal(query.colour, "Oak");
    assert.equal(query.page, "2");
    assert.equal(query.page_size, String(PAGE_SIZE));
  });

  it("maps sorts to the products service's orderings, and relevance to none", () => {
    assert.equal(toProductsQuery(parseSearchParams({ sort: "newest" })).ordering, "-created_at");
    assert.equal(toProductsQuery(parseSearchParams({ sort: "price_asc" })).ordering, "min_price");
    assert.equal(toProductsQuery(parseSearchParams({ sort: "price_desc" })).ordering, "-min_price");
    assert.equal(toProductsQuery(parseSearchParams({ search: "desk" })).ordering, "");
  });

  it("keeps on-sale browsing on the products service", () => {
    const query = toProductsQuery(parseSearchParams({ on_sale: "true" }));

    assert.equal(query.on_sale, "true");
    assert.equal(query.search, "");
  });
});

describe("buildHref", () => {
  it("keeps the other filters and starts again from page 1 when a filter changes", () => {
    const params = parseSearchParams({ search: "desk", colour: "Oak", page: "3", sort: "price_asc" });

    assert.equal(buildHref(params, { size: "M" }), "/products?search=desk&colour=Oak&size=M&sort=price_asc");
  });

  it("keeps the page when paging, and leaves page 1 out of the URL", () => {
    const params = parseSearchParams({ search: "desk", page: "2" });

    assert.equal(buildHref(params, { page: 3 }), "/products?search=desk&sort=relevance&page=3");
    assert.equal(buildHref(params, { page: 1 }), "/products?search=desk&sort=relevance");
  });

  it("removes a filter when its value is cleared", () => {
    const params = parseSearchParams({ search: "desk", colour: "Oak" });

    assert.equal(buildHref(params, { colour: "" }), "/products?search=desk&sort=relevance");
  });
});

describe("normalizeSearch", () => {
  it("shapes hits like product listings, so one tile renders both", () => {
    const data = normalizeSearch({
      total: 1,
      results: [{
        product_id: "p1", slug: "nordic-oak-desk", name: "Nordic Oak Desk", brand: "Nordic",
        image_url: "https://example.test/desk.png", price_min: "229.00", price_max: "259.00",
      }],
      facets: { colours: [], sizes: [], categories: [], price: { min: "229.00", max: "259.00" } },
    });

    assert.equal(data.count, 1);
    assert.deepEqual(data.results[0], {
      id: "p1",
      slug: "nordic-oak-desk",
      name: "Nordic Oak Desk",
      brand: "Nordic",
      thumbnail: "https://example.test/desk.png",
      min_price: "229.00",
      compare_at_price: null,
      discount_percent: 0,
    });
    assert.equal(data.facets.price.max, "259.00");
  });
});

describe("suggestions and keyboard", () => {
  it("only asks for suggestions once there are two characters", () => {
    assert.equal(shouldSuggest("n"), false);
    assert.equal(shouldSuggest("  n "), false);
    assert.equal(shouldSuggest("no"), true);
  });

  it("encodes the query in the suggest URL", () => {
    assert.equal(suggestUrl(" desk & lamp "), "/api/v1/search/suggest?q=desk+%26+lamp");
  });

  it("moves the highlight with the arrows and wraps at both ends", () => {
    assert.equal(nextIndex(-1, 1, 3), 0);
    assert.equal(nextIndex(-1, -1, 3), 2);
    assert.equal(nextIndex(2, 1, 3), 0);
    assert.equal(nextIndex(0, -1, 3), 2);
    assert.equal(nextIndex(0, 1, 0), -1);
  });
});
