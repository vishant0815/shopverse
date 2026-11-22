// Shapes the analytics API's "bought together" answer for the product page. No server imports here,
// so these rules can be tested alone.

// How many products the product page shows.
export const SHOWN = 3;

// Keeps the entries the block can link to and show, in the order the API gave them, up to SHOWN.
export function visibleRecommendations(payload) {
  const items = Array.isArray(payload?.items) ? payload.items : [];
  return items
    .filter((item) => item && typeof item.product_id === "string" && item.name && item.slug)
    .slice(0, SHOWN)
    .map(({ product_id, name, slug, image_url }) => ({ product_id, name, slug, image_url: image_url || "" }));
}
