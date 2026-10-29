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

---

## 006: Services verify JWTs themselves with a shared signing key

**Decision:** Only the users service issues tokens. Every other service verifies the token's signature with the same `JWT_SIGNING_KEY` and trusts the `user_id` and `role` claims inside it.

**Why:** No network call to the users service on every request, so the product catalogue keeps working even if the users service is slow or down. It also keeps the services decoupled: the product service has no user table at all.

**Trade-off:** Every service holding the key could also sign tokens, and a role change only takes effect when the user's access token expires (at most 15 minutes). The next step would be asymmetric keys (RS256): the users service signs with a private key, and other services only get the public key, so they can verify but never issue tokens.

---

## 007: Prices on variants, stock in a separate service, soft deletes

**Decision:** A product has variants (colour, size), and each variant has its own SKU and price. Stock is not stored in the product service. Products are archived, and variants and categories are deactivated, instead of being deleted.

**Why:** Different sizes or storage options often cost different amounts, so the price belongs to the thing being bought. Stock changes far more often than catalogue data and needs locking during checkout, so it belongs to the inventory service. Orders will refer to products and SKUs long after they stop being sold, so those rows must not disappear.

---

## 008: Idempotent checkout

**Decision:** Checkout accepts an `Idempotency-Key` header. The key is stored on the order with a unique constraint per user. A repeated request with the same key returns the original order instead of creating another.

**Why:** Networks drop responses and people double-click. Without this, a retry after a timeout creates a second order, and later a second payment. The key is checked three times: before doing any work, again after taking the cart lock (a duplicate may have been waiting on that lock while the first request finished), and finally by the database constraint if two requests still race.

**Trade-off:** The client has to generate and send a key. That is standard practice (Stripe's API works the same way), and checkout still works without one.

---

## 009: Server-side pricing, snapshots, and no locks during network calls

**Decision:** The cart stores only variant ids and quantities. At checkout the orders service fetches live prices from the product service, then locks the cart and verifies it hasn't changed before creating the order. The order copies names, SKUs, prices, sellers and the shipping address.

**Why:** Prices from the client can't be trusted. Fetching prices before taking the lock means a slow product service never holds database rows locked; comparing the cart afterwards catches anything that changed in between. Snapshots keep orders accurate forever, even when products are renamed, repriced or archived.

**Trade-off:** Checkout depends on the product service being up; if it isn't, checkout fails cleanly with `503` and the cart is kept. Later, Kafka events can keep a local price cache in the orders service to remove that dependency.

---

## 010: Order lifecycle as an explicit state machine

**Decision:** The allowed status changes are listed in one place (`Order.TRANSITIONS`). Every change goes through `move_to()`, which writes a history row with who made the change.

**Why:** Status bugs in e-commerce are expensive: shipping an unpaid order, or refunding a delivered one twice. One table of legal moves makes the rules easy to read, test and extend, and the history gives a full audit trail for support and disputes.

---

## 011: Payments in FastAPI behind a provider interface

**Decision:** The payments service is written in FastAPI with SQLAlchemy and Alembic, unlike the Django services. Stripe sits behind a small `PaymentProvider` interface, with a fake provider for local use.

**Why:** Payments is a small, focused service with no admin screens, so Django's extras aren't needed. FastAPI gives typed request validation and generated API docs. Using two frameworks also mirrors real companies, where services are often built with different stacks. The provider interface means anyone can clone the repository and complete a payment without a Stripe account, tests need no network access, and adding another provider (e.g. PayPal) doesn't touch the payment logic.

**Trade-off:** Two frameworks means two sets of conventions to maintain.

---

## 012: Webhooks as the source of truth for payment success

**Decision:** An order is marked paid only when a signed Stripe webhook says so, never because the browser reports success. Every event id is stored so duplicates are ignored. If the orders service can't be reached, the webhook answers `503` and saves nothing.

**Why:** The browser can be closed, lose its connection, or be tampered with; Stripe's signed webhook can't. Stripe delivers events at least once and retries until it gets a `2xx`, so the handler must be idempotent, and returning `503` on failure turns Stripe's retries into free, automatic recovery.

**Trade-off:** There's a short delay between the customer paying and the order showing as paid. The next step is to publish a `payment.succeeded` event to Kafka instead of calling the orders service directly, which removes the direct dependency between the two services.
