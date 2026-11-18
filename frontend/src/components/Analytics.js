"use client";

// Renders nothing. Each one records one storefront event when the page shows it.

import { useEffect } from "react";

import { productSource, tracker } from "@/lib/clickstream";

export function TrackProductView({ productId }) {
  useEffect(() => {
    tracker().track("product_view", { product_id: productId, source: productSource(document.referrer) });
  }, [productId]);
  return null;
}

export function TrackSearch({ query, resultCount }) {
  useEffect(() => {
    tracker().track("search", { query: query.slice(0, 200), result_count: resultCount });
  }, [query, resultCount]);
  return null;
}
