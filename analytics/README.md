# Analytics: Spark jobs

Spark jobs that turn the platform's events into tables. The first is the clickstream job.

## Clickstream job (`clickstream/`)

Reads `clickstream.events` (from the collector in `services/clickstream`) and `orders.events`, and writes Parquet to `ANALYTICS_OUTPUT_DIR` (default `/data/analytics`):

| Table | What a row is |
|---|---|
| `raw_events` | One accepted storefront event, partitioned by `date` and `hour`. |
| `product_totals` | One product in one five-minute window: `views`, `add_to_carts`, `units_sold`. |
| `search_terms` | One search term in one five-minute window: `searches`. |

- Repeats are dropped by `event_id` within a ten-minute watermark.
- Purchases are the items of `OrderConfirmed` events. Other order events are ignored.
- A message that can't be read as an event goes to `clickstream.events.dlq`, with its original text.
- The job uses Spark's `max` watermark policy, so one quiet input doesn't hold every window open. See decision 028.

Files: `transforms.py` (the DataFrame logic, no Kafka), `pipeline.py` (the streaming queries, no Kafka), `job.py` (Kafka in and out, run by `spark-submit`).

## Running and testing

```
pip install -r requirements-dev.txt        # PySpark 4.0; needs Java 17 or 21
pytest
```

The tests run the pipeline on text files standing in for Kafka. In the container, `spark-submit` downloads the Kafka connector on first start, so the container needs network access to Maven Central the first time.
