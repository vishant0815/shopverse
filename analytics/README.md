# Analytics: Spark jobs

Spark jobs that turn the platform's events into tables. The one job is the clickstream job: it reads the storefront, order and catalogue topics and writes tables for the seller dashboard and for later analysis.

## The job (`clickstream/`)

Reads `clickstream.events` (from the collector in `services/clickstream`), `orders.events` and `catalog.products`.

Parquet, on the `analytics_data` volume (`ANALYTICS_OUTPUT_DIR`, default `/data/analytics`):

| Table | What a row is |
|---|---|
| `raw_events` | One accepted storefront event, partitioned by `date` and `hour`. |
| `product_totals` | One product in one five-minute window: `views`, `add_to_carts`, `units_sold`. |
| `search_terms` | One search term in one five-minute window: `searches`. |

Postgres, in `analytics_db` (`ANALYTICS_DATABASE_URL`; schema in `infra/postgres/analytics/schema.sql`, applied on start):

| Table | What a row is |
|---|---|
| `product_listings` | One product: its seller, name, slug and image. The newest catalogue revision wins. |
| `product_daily` | One product on one UTC day: `views`, `add_to_carts`, `units_sold`. Rewritten as the day's totals change. |

The `analytics-api` service (`services/analytics-api`) reads the Postgres tables for the seller dashboard. See decision 029.

- Repeats are dropped by `event_id` within a ten-minute watermark.
- Purchases are the items of `OrderConfirmed` events. Other order events are ignored.
- A message that can't be read as an event goes to `clickstream.events.dlq`, with its original text.
- The job uses Spark's `max` watermark policy, so one quiet input doesn't hold every window open. See decision 028.
- Every write is an upsert, so a batch replayed after a restart leaves the same numbers.

Files: `transforms.py` (the DataFrame logic, no Kafka), `pipeline.py` (the streaming queries, no Kafka or database), `postgres.py` (the upserts into Postgres), `job.py` (Kafka in, Postgres and Kafka out, run by `spark-submit`).

### Configuration

| Variable | Purpose |
|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | Where the brokers are, e.g. `kafka:9092`. |
| `ANALYTICS_OUTPUT_DIR` | Where the Parquet tables and checkpoints go. Default `/data/analytics`. |
| `ANALYTICS_DATABASE_URL` | The analytics database, e.g. `postgresql://user:pass@postgres:5432/analytics_db`. |
| `ANALYTICS_SCHEMA_PATH` | The schema file applied on start. Default `/schema/schema.sql` (mounted from `infra/postgres/analytics`). |

## Running and testing

```
pip install -r requirements-dev.txt        # PySpark 4.0 and psycopg; needs Java 17 or 21
pytest
```

The pipeline tests run on text files standing in for Kafka and in-memory sinks. The Postgres tests run against a real database that gets emptied, so name one on purpose:

```
createdb analytics_test
ANALYTICS_TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/analytics_test pytest
```

Without `ANALYTICS_TEST_DATABASE_URL` the Postgres tests are skipped.

In the container, `spark-submit` downloads the Kafka connector on first start, so the container needs network access to Maven Central the first time.
