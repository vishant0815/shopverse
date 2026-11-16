# Notifications service

A Kafka consumer that sends the customer emails: order placed, order confirmed, order cancelled, payment failed and refund issued. It has no HTTP port. It reacts to events from the orders, payments and users services (see [docs/events.md](../../docs/events.md)) and keeps its own copy of each customer's name and email.

## Emails

| Email | Triggered by | Topic |
|---|---|---|
| Order placed (pay within 15 minutes) | `OrderPlaced` | orders.events |
| Order confirmed | `OrderConfirmed` | orders.events |
| Order cancelled | `OrderCancelled` | orders.events |
| Payment failed | `PaymentFailed` | payments.events |
| Refund issued | `PaymentRefunded` | payments.events |

Each email has a plain-text and an HTML version, built from the same facts. Values from events are escaped in the HTML.

## Contact details

Customer contact details come from `UserRegistered` and `UserContactChanged` on users.events. They are kept in the `recipients` table, so sending an email never calls the users service. Payment and cancellation events carry only the order number, so `order_customers` maps each order to its customer, recorded from `OrderPlaced`.

A message whose customer isn't known yet waits up to `RECIPIENT_WAIT_SECONDS` (two minutes by default), then goes to the dead-letter topic. Other failures are retried three times, then dead-lettered. A dead-lettered message keeps the reason in its `error` header.

## Delivery and idempotency

- Each message is handled in one database transaction with its `processed_messages` row, so a repeated message is skipped.
- An email is sent inside that transaction. A crash between sending and committing can send the email twice on restart. This is accepted, as recorded in decision 027.
- `notification_log` holds one row per email sent.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | `notifications_db`, required, `localhost`, `5432` | Postgres |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Kafka |
| `SMTP_HOST`, `SMTP_PORT` | `localhost`, `1025` | Mail server (Mailpit in development) |
| `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_STARTTLS` | empty, empty, `false` | Set for a real relay that needs login and TLS |
| `MAIL_FROM` | `Shopverse <orders@shopverse.example>` | Sender address |
| `SITE_URL` | `http://localhost:3002` | Base of the links in the emails |
| `PAYMENT_WINDOW_MINUTES` | `15` | The checkout hold. Must match the orders service |
| `RECIPIENT_WAIT_SECONDS` | `120` | How long a message waits for a customer's contact details |

## Running it

With the stack up, `docker compose up notifications-worker mailpit` starts the worker and the mail catcher. Every email it sends appears in the Mailpit inbox at http://localhost:8025.

Tests need Postgres. They build a `notifications_test` database from the real migrations:

```bash
cd services/notifications
pip install -r requirements-dev.txt
DB_USER=shopverse DB_PASSWORD=shopverse DB_HOST=localhost DB_PORT=5432 pytest
```

The service runs `alembic upgrade head` on start, as the payments service does.
