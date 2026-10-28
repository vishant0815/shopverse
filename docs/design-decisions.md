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

---

## 004: JWT with the refresh token in an httpOnly cookie

**Decision:** Login returns a short-lived access token (15 minutes) in the response body and a longer-lived refresh token (7 days) in an `httpOnly`, `SameSite=Lax` cookie scoped to `/api/v1/auth/`.

**Why:** JWTs are stateless, so every service can verify a request on its own without calling the users service. Keeping the refresh token out of JavaScript's reach means an XSS bug can't steal a long-lived session, and the access token in memory expires quickly. `SameSite=Lax` stops other sites from triggering a refresh with the user's cookie.

**Trade-off:** A JWT can't be revoked before it expires. That's why access tokens are short-lived, and why refresh tokens are rotated on every use and blacklisted on logout or password change.

---

## 005: Email login, roles on the user, UUID primary keys

**Decision:** A custom user model with email as the login field, a `role` field (`customer`, `seller`, `admin`) and UUID primary keys.

**Why:** Custom user models must be set up before the first migration; changing later is painful. A single `role` field keeps authorisation simple and is copied into the JWT, so other services can check it. UUIDs can't be guessed or counted, and are safe to use in events across services.

**Trade-off:** UUID indexes are larger than integer ones. At this scale that cost is small compared with the security and cross-service benefits.
