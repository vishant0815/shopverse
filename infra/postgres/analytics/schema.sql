-- Tables for the seller analytics. The analytics job (Spark) writes them and the analytics API
-- reads them. The job runs this file on start-up; every statement can run again safely.

-- One row per product, from the catalogue's ProductUpserted messages. Only the newest revision is
-- kept, so an old message that arrives late never overwrites a newer one.
CREATE TABLE IF NOT EXISTS product_listings (
    product_id uuid PRIMARY KEY,
    seller_id uuid NOT NULL,
    name text NOT NULL,
    slug text NOT NULL,
    image_url text NOT NULL DEFAULT '',
    revision integer NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS product_listings_seller_idx ON product_listings (seller_id);

-- Views, add-to-cart events and units sold for each product on each UTC day. The job rewrites a
-- day's row each time its totals change, so the numbers always match what Spark has counted.
CREATE TABLE IF NOT EXISTS product_daily (
    product_id uuid NOT NULL,
    day date NOT NULL,
    views integer NOT NULL DEFAULT 0,
    add_to_carts integer NOT NULL DEFAULT 0,
    units_sold integer NOT NULL DEFAULT 0,
    PRIMARY KEY (product_id, day)
);

-- How many confirmed orders each two products were bought in together, stored in both directions so
-- one lookup by product_id gives its pairs. The job rewrites a row when its running count changes.
CREATE TABLE IF NOT EXISTS product_pairs (
    product_id uuid NOT NULL,
    related_id uuid NOT NULL,
    shared_orders integer NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (product_id, related_id)
);

CREATE INDEX IF NOT EXISTS product_pairs_ranking_idx ON product_pairs (product_id, shared_orders DESC);
