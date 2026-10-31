// Catalogue reads done on the server, so product pages arrive fully rendered
// (fast first paint, and search engines can read them). Runs in Node, not the browser.
import "server-only";

const PRODUCTS = process.env.PRODUCTS_API_URL || "http://localhost:8002";

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

export function findCategory(tree, slug) {
  for (const node of tree || []) {
    if (node.slug === slug) return node;
    const found = findCategory(node.children, slug);
    if (found) return found;
  }
  return null;
}
