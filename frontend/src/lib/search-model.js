// Pure helpers for storefront search: URL parsing, API parameters and result shapes.
// No network and no server-only imports, so `npm test` can run them directly.

export const PAGE_SIZE = 12;

export const SORT_OPTIONS = [
  ["relevance", "Relevance"],
  ["newest", "Newest"],
  ["price_asc", "Price: low to high"],
  ["price_desc", "Price: high to low"],
];

const SORT_KEYS = new Set(SORT_OPTIONS.map(([key]) => key));

// The products service (used for on-sale browsing and when search is down) names its orderings differently.
const PRODUCTS_ORDERING = { newest: "-created_at", price_asc: "min_price", price_desc: "-min_price" };

const SUGGEST_MIN_LENGTH = 2;

// Repeated query keys arrive as arrays; only the first value counts.
const first = (value) => (Array.isArray(value) ? value[0] : value) ?? "";

function clean(value, max) {
  return String(first(value)).trim().slice(0, max);
}

function priceParam(value) {
  const raw = String(first(value)).trim();
  const number = Number(raw);
  return raw !== "" && Number.isFinite(number) && number >= 0 && number <= 1_000_000 ? String(number) : "";
}

// Reads the page's URL into the filters it uses. Bad values are dropped, never passed on to the APIs.
// The keys are the URL names: search, category, brand, colour, size, min_price, max_price, sort, on_sale, page.
export function parseSearchParams(raw) {
  const search = clean(raw.search, 100);
  let minPrice = priceParam(raw.min_price);
  let maxPrice = priceParam(raw.max_price);
  if (minPrice && maxPrice && Number(minPrice) > Number(maxPrice)) {
    [minPrice, maxPrice] = [maxPrice, minPrice];
  }
  const sort = first(raw.sort);
  const page = Number.parseInt(first(raw.page), 10);
  return {
    search,
    category: clean(raw.category, 100),
    brand: clean(raw.brand, 100),
    colour: clean(raw.colour, 50),
    size: clean(raw.size, 20),
    min_price: minPrice,
    max_price: maxPrice,
    sort: SORT_KEYS.has(sort) ? sort : search ? "relevance" : "newest",
    on_sale: first(raw.on_sale) === "true" ? "true" : "",
    page: Number.isFinite(page) && page >= 1 ? Math.min(page, 200) : 1,
  };
}

// Link to this page with some values changed. Empty values and page 1 are left out of the URL,
// and changing a filter starts again from page 1 unless a page is given.
export function buildHref(params, changes = {}) {
  const next = { ...params, ...changes };
  if (!("page" in changes)) delete next.page;
  const query = new URLSearchParams(
    Object.entries(next)
      .filter(([key, value]) => value !== "" && value !== null && value !== undefined)
      .filter(([key, value]) => !(key === "page" && Number(value) <= 1))
      .map(([key, value]) => [key, String(value)]),
  );
  return `/products${query.toString() ? `?${query}` : ""}`;
}

// Parameters for GET /api/v1/search/products.
export function toSearchQuery(params) {
  return {
    q: params.search,
    category: params.category,
    brand: params.brand,
    colour: params.colour,
    size: params.size,
    min_price: params.min_price,
    max_price: params.max_price,
    sort: params.sort,
    page: String(params.page),
    page_size: String(PAGE_SIZE),
  };
}

// Parameters for the products service: on-sale browsing, and the stand-in when search is down.
export function toProductsQuery(params) {
  return {
    search: params.search,
    category: params.category,
    brand: params.brand,
    colour: params.colour,
    size: params.size,
    min_price: params.min_price,
    max_price: params.max_price,
    on_sale: params.on_sale,
    ordering: PRODUCTS_ORDERING[params.sort] ?? "",
    page: String(params.page),
    page_size: String(PAGE_SIZE),
  };
}

// Search hits are shaped like product-service listings, so the same tile renders both.
export function normalizeSearch(data) {
  return {
    count: data.total,
    results: data.results.map((hit) => ({
      id: hit.product_id,
      slug: hit.slug,
      name: hit.name,
      brand: hit.brand,
      thumbnail: hit.image_url,
      min_price: hit.price_min,
      compare_at_price: null,
      discount_percent: 0,
    })),
    facets: data.facets,
  };
}

export function shouldSuggest(query) {
  return query.trim().length >= SUGGEST_MIN_LENGTH;
}

export function suggestUrl(query) {
  return `/api/v1/search/suggest?${new URLSearchParams({ q: query.trim() })}`;
}

// Moves the highlighted suggestion with the arrow keys, wrapping at both ends. -1 means none is highlighted.
export function nextIndex(current, step, length) {
  if (length === 0) return -1;
  if (current < 0) return step > 0 ? 0 : length - 1;
  return (current + step + length) % length;
}
