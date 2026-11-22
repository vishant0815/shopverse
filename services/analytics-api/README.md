# Analytics API

Serves two things, both read from the tables the Spark job writes to Postgres (see `analytics/README.md` and decisions 029 and 030). The first is the seller dashboard's numbers: product views, add-to-carts and units sold, by day and by product. The second is the storefront's "frequently bought together" recommendations. It has no writes and no Kafka.

## Endpoint

`GET /api/v1/seller/analytics/?days=7` (or `days=30`). The gateway forwards it at the same path.

- It answers only a seller's access token. A missing, expired or refresh token gets `401`; a customer's token gets `403`.
- Every number is joined to the signed-in seller's own product listings. The request has no product or seller id, so there is nothing to change to see someone else's figures.
- The range ends today (UTC) and covers `days` days. Each day is in `daily`, including days with no activity, oldest first.
- `totals` covers every product of the seller. `products` lists up to 50, most units sold first.
- `add_to_cart_rate` is add-to-cart events divided by product views, or `null` when nothing was viewed.
- `503` means the analytics tables don't exist yet, because the Spark job hasn't started.

Example response, abridged:

```json
{
  "from": "2026-11-15", "to": "2026-11-21", "days": 7,
  "totals": {"views": 120, "add_to_carts": 14, "units_sold": 9, "add_to_cart_rate": 0.117},
  "daily": [{"date": "2026-11-15", "views": 0, "add_to_carts": 0, "units_sold": 0}],
  "products": [{"product_id": "…", "name": "Desk Lamp", "slug": "desk-lamp", "image_url": "", "views": 80, "add_to_carts": 9, "units_sold": 6}]
}
```

## Recommendations

`GET /api/v1/recommendations/products/{product_id}/bought-together`. Anyone can call it, with or without a token. The gateway forwards it at the same path.

- It returns `{"product_id": ..., "items": [...]}`, with up to three products that were in at least two confirmed orders with this one, most shared first.
- Each item has `product_id`, `name`, `slug` and `image_url`. A product without a listing is left out.
- The answer carries `Cache-Control: public, max-age=120`, because the job refreshes the pairs every few minutes.
- A malformed id gets `422`. `503` means the pairs table doesn't exist yet.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `JWT_SIGNING_KEY` | required | Verifies tokens. The same key the users service signs with (at least 32 characters outside debug). |
| `DATABASE_URL` | required | The analytics database, e.g. `postgresql://user:pass@postgres:5432/analytics_db`. |
| `DEBUG` | `false` | Allows a shorter signing key for local work. |

Each request opens one connection and closes it. The reads are small, so there is no pool yet.

## Running and testing

```
pip install -r requirements-dev.txt
ANALYTICS_TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/analytics_test pytest
```

The tests empty the analytics tables, so `ANALYTICS_TEST_DATABASE_URL` must name a database that can be emptied. The tests stop with a message if it isn't set. They apply the same `infra/postgres/analytics/schema.sql` the Spark job applies.
