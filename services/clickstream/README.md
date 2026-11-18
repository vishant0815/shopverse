# Clickstream collector

Accepts the storefront's analytics events (product views, searches and add-to-cart) and queues them on Kafka for the Spark job in `analytics/`. It has no database.

## Endpoint

`POST /api/v1/clickstream/events` takes `{"events": [...]}` with up to 100 events and answers `202 {"accepted": n}` once they are queued. The gateway forwards it at the same path.

- Each event is checked against its schema. An unknown type, an unknown field, a bad id, a search over 200 characters or a time more than five minutes ahead of the server's clock fails the whole batch with `422`. The storefront drops a batch the collector refuses for good.
- A `user_id` in the body is refused. The user id comes from a signed-in shopper's token, if there is a valid one. An expired or broken token records the event as anonymous.
- A `503` means the local queue is full. Send the same batch again: each event has an id, so Spark counts repeats once.

`accepted` means queued, not stored by Kafka. See `docs/events.md` ("Storefront events") and decision 028.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `JWT_SIGNING_KEY` | required | Reads the user id from a token. The same key the users service signs with. |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Where the brokers are. |
| `CLICKSTREAM_TOPIC` | `clickstream.events` | Topic the events go to. |
| `MAX_CLOCK_SKEW_SECONDS` | `300` | How far ahead of the server clock an event may be stamped. |

At start-up the collector creates `clickstream.events` and `clickstream.events.dlq` if they don't exist, because Kafka doesn't create topics automatically here.

## Running and testing

```
pip install -r requirements-dev.txt
JWT_SIGNING_KEY=… pytest
```

The tests use a fake publisher, so they don't need Kafka. The full path, collector to Kafka to Spark, was run against a real broker when this service was built.
