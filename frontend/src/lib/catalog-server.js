// Catalogue reads done on the server, so product pages arrive fully rendered
// (fast first paint, and search engines can read them). Runs in Node, not the browser.
import "server-only";

const PRODUCTS = process.env.PRODUCTS_API_URL || "http://localhost:8002";
const INVENTORY = process.env.INVENTORY_API_URL || "http://localhost:8005";

export class CatalogueDown extends Error {}

async function get(path, { revalidate = 60 } = {}) {
  let response;
  try {
    response = await fetch(`${PRODUCTS}/api/v1/${path}`, { next: { revalidate } });
  } catch {
    throw new CatalogueDown();
  }
  if (response.status === 404) return null;
  if (!response.ok) throw new CatalogueDown();
  return response.json();
}

export function getCategoryTree() {
  return get("categories/tree/", { revalidate: 300 });
}

export function getProducts(params = {}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value) search.set(key, value);
  }
  return get(`products/?${search}`, { revalidate: 30 });
}

export function getProduct(slug) {
  return get(`products/${encodeURIComponent(slug)}/`, { revalidate: 30 });
}

// How many of each variant can be bought right now: { [variantId]: available }.
// Stock is a convenience on the product page, not a guarantee (checkout checks again),
// so if inventory is unreachable the page still works and just doesn't show stock levels.
export async function getAvailability(variantIds) {
  if (!variantIds.length) return {};
  try {
    const response = await fetch(`${INVENTORY}/api/v1/inventory/availability?variant_ids=${variantIds.join(",")}`,
      { next: { revalidate: 10 } });
    if (!response.ok) return {};
    const { results } = await response.json();
    return Object.fromEntries(results.map((row) => [row.variant_id, row.available]));
  } catch {
    return {};
  }
}

export function findCategory(tree, slug) {
  for (const node of tree || []) {
    if (node.slug === slug) return node;
    const found = findCategory(node.children, slug);
    if (found) return found;
  }
  return null;
}
