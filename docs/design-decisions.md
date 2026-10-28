# Design decisions

A record of the main architecture choices in Shopverse and the reasons behind them. New entries are added as the project grows.

---

## 001: Monorepo

**Decision:** All services, the frontend, infrastructure and docs live in one repository.

**Why:** One place to clone, one `docker compose up` to run everything, and changes that touch several services can be reviewed in a single pull request. Each service still has its own folder, dependencies and tests, so it can be split into its own repository later if needed.

---

## 002: Database per service

**Decision:** Each service gets its own PostgreSQL database (`users_db`, `products_db`, `orders_db`, ...). Locally they share one Postgres container to save resources; the databases are created by `infra/postgres/init/01-create-service-databases.sh`.

**Why:** A service owning its data means its schema can change without breaking other services, and no service can couple itself to another's tables. Data that another service needs is shared through APIs or Kafka events instead.

**Trade-off:** No cross-service joins or foreign keys. Consistency across services is handled with events and the Saga pattern (see a later entry).

---

## 003: Redis for cache, sessions and stock locks

**Decision:** Redis is part of the base infrastructure from the start.

**Why:** It covers three needs with one tool: caching hot reads (product pages, categories), short-lived data (sessions, rate-limit counters), and atomic operations for reserving stock during checkout.
