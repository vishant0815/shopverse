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

**Status:** Partly superseded by 018. The webhook still decides what happened, but it no longer calls the orders service: the outcome and the event for orders are written together, and a database failure is what makes Stripe retry.

---

## 013: The storefront as the browser's only entry point

> **Replaced by 016.** The gateway now sits in front of the storefront. The one-origin idea below still holds.

**Decision:** The browser talks only to the Next.js storefront. Its rewrites forward `/api/v1/...` paths, unchanged, to the right service. Catalogue pages are rendered on the server; signed-in pages run in the browser.

**Why:** One origin means no CORS rules to get wrong, and the refresh cookie (scoped to `/api/v1/auth/`) works without changes because paths are forwarded as they are. Server rendering makes product pages fast and readable by search engines, while basket and order pages depend on the signed-in user and gain nothing from it.

**Trade-off:** The storefront is now also a simple gateway, so it doesn't do what a real one would: rate limiting across all services, request logging, or TLS termination. A dedicated API gateway (Nginx or Kong) is on the roadmap and would take over this role, leaving the storefront to only render pages.

---

## 014: Themes with CSS variables and a pre-paint script

**Decision:** Every colour is a CSS variable, defined once for the dark theme and once for the light theme, and switched by a `data-theme` attribute on `<html>`. A small inline script in `<head>` sets that attribute before the page is drawn, from the saved choice or the device setting. React never sets it.

**Why:** Components only use names like `text-accent` and `text-power`, so a whole theme changes in one place, and the light theme's "dark red" is the same variable as the dark theme's bright red. Setting the theme before the first paint avoids the common flash of the wrong theme on server-rendered pages. Leaving the attribute out of React's output matters: on pages React renders entirely in the browser (such as the 404 page), React would otherwise overwrite the saved theme. An early version had exactly that bug, found by the browser tests.

**Trade-off:** The saved choice lives in the browser (`localStorage`), so it doesn't follow a user to another device. Saving it on the user's profile is a small follow-up if needed.

---

## 015: The seller and admin panel lives inside the storefront

**Decision:** The panels are pages of the existing Next.js app (`/seller`, `/admin`) rather than a separate admin app. They reuse the same components, theme and API proxy, and call the same service endpoints the rest of the platform already exposes. The only new backend code is two read-only summary endpoints for the dashboard and the order tabs.

**Why:** A second app would mean a second build, a second set of components and a second place where sign-in has to work, for pages that mostly list and edit data the services already serve. The role check in the browser only decides what to show; every request is still checked by the service that owns the data, so a customer who opens `/admin` by hand gets nothing from the API either.

**Trade-off:** Customers download a little of the panel code as shared chunks, and a bug in a shared component can affect both the shop and the panel. If the panel grows large (bulk uploads, reports), splitting it into its own app is straightforward because it already only talks to the APIs.

---

## 016: A custom gateway in front of everything, including the storefront

**Decision:** A small FastAPI gateway is the only published entry point. It serves the whole site: pages go to the storefront, and `/api/...` goes to the services after a token check and a rate limit. It replaces the storefront's role as a proxy (013), and also stands in for the Nginx gateway first planned.

**Why the gateway is in front, not behind the storefront:** The first version put it behind Next.js, which forwards API calls to it. Testing showed two problems. First, Next.js passes on whatever `X-Forwarded-For` the browser sends, so a client could choose its own address and dodge per-address limits. Second, it adds nothing when the header is missing, so every anonymous visitor shared one address: the storefront's. Rate limits by address only work if the component doing the limiting sees the real connection. So the gateway became the edge, and the storefront is no longer published.

**Why a custom gateway, not Nginx or Kong:**
- **Redis-backed limits.** The rules needed limits counted per signed-in user once a token is verified, and per address before that, kept in Redis so every replica agrees. Nginx's built-in limiter keeps its counts in each instance's memory, and the alternatives are Lua modules or Kong plugins.
- **Readable and testable.** A few hundred lines of Python, with 92 tests, show exactly how routing, limits and failures behave.

**Trade-off:** It's one more service to run and keep fast; locally it adds about 4 ms per request. TLS termination and caching static files are still left to whatever sits in front in production (a load balancer or CDN). Setting `TRUSTED_PROXY_HOPS=1` makes the gateway trust exactly that one hop. Moving to Kong or Envoy later is straightforward, because services only ever see plain HTTP with the usual forwarding headers.

---

## 017: Token buckets in Redis that fail open

**Decision:** Each caller gets a token bucket per kind of request (sign-in, token refresh, checkout, everything else), kept in Redis and updated by one Lua script. Callers are counted per account when signed in, and per address otherwise. If Redis can't be reached, requests are let through and a warning is logged.

**Why:**
- **Shape.** A token bucket allows short bursts, like a page that makes several calls at once, while stopping a steady flood. A fixed one-minute window would allow double the limit across a window boundary.
- **No races.** Doing the check and the take in one script is atomic, so concurrent requests can't overspend; a test proves it with 50 requests at once against a bucket of 10. The script uses Redis's clock, so gateways with drifting clocks agree.
- **Refresh has its own limit.** Token refresh happens on every page load, so sharing the sign-in limit would sign people out for browsing quickly. The users service had exactly that problem, and the browser tests hit it; refresh now has its own limit there too.

**Trade-off:** Failing open means a Redis outage removes rate limiting until Redis is back. The alternative, failing closed, would turn a cache outage into a full shop outage. The users service keeps its own sign-in limit as a second line, so brute-forcing passwords stays slowed even then.

---

## 018: Kafka between services, with a transactional outbox

**Decision:** Services tell each other about changes as events on Kafka. A service never publishes straight from a request: the event is written to an `outbox` table in the same database transaction as the change, and a relay in the service's worker sends unsent rows in order and marks them sent. Consumers record every message id they handle in `processed_messages`, in the same transaction as their own changes, and commit the Kafka offset only after that.

**Why:**
- **No lost or phantom messages.** A change and its event commit together or not at all. Publishing after commit would lose the event if the process died in between; publishing before would announce a change that never happened.
- **At-least-once delivery, exactly-once effects.** Kafka redelivers after a crash, and the relay can send a message twice. Recording message ids makes the second handling a no-op, so a duplicate refund or a second stock reservation can't happen.
- **Order where it matters.** Rows are sent by a sequence number, not a timestamp: every row in one transaction shares the same `now()`. Messages about one order are written under that order's lock, so their order is kept.

**Trade-off:** Each service runs one more process (its worker), and messages reach other services after a short delay rather than immediately. The outbox table needs cleaning up once rows are sent. Full detail, with the topics and message shapes, is in [docs/events.md](events.md).

---

## 019: Checkout as a saga, with orders as the orchestrator

**Decision:** Placing an order is a saga run by the orders service. It asks inventory to reserve stock, waits for the reply, leaves the customer 15 minutes to pay, and asks inventory to commit the stock once payment is confirmed. Each step has an undo: releasing stock, or refunding the money. The orders service keeps the saga's state next to the order, and a periodic sweep cancels checkouts that run out of time.

**Why:**
- **No distributed transaction.** Orders, inventory and payments each have their own database, so there's no single commit that covers all three. A saga is a sequence of local steps that can each be undone.
- **One place to look.** Only orders decides what a checkout's outcome is. Inventory and payments answer commands and don't call each other.
- **Money that lands for a dead order goes back.** If a payment arrives after its order was cancelled, the saga asks for a refund. An amount that doesn't match the order total is refunded too, rather than marking the order paid.

**Trade-off:** The customer sees "Checking stock" for a moment instead of an instant result, and the order page polls until the saga settles. A saga that gets stuck (say, inventory is down for longer than two minutes) is cancelled by the timeout rather than retried forever, which is the right failure for a shop but means a customer may need to try again.

---

## 020: Stock is held at checkout and committed only when paid

**Decision:** Inventory keeps `on_hand` and `reserved` for each option, with `available = on_hand − reserved`. A reservation takes units from `available` when the order starts, and turns into a sale (reducing `on_hand`) when payment is confirmed. Reservations lock their rows in variant-id order, and a database check keeps `reserved` at or below `on_hand`.

**Why:**
- **Holding is cheap to undo.** An abandoned checkout only moves a counter, so nothing is lost when a customer walks away.
- **Two shoppers can't both get the last unit.** The lock on the rows serialises reservations for the same option, and locking in a fixed order stops two multi-item checkouts from deadlocking.
- **A cancelled sale goes back on the shelf.** Releasing a committed reservation adds the units back to `on_hand`, so cancelling a paid order undoes the sale completely.

**Trade-off:** A reservation holds stock for up to 15 minutes even if the customer never pays, so a popular item can look sold out while others are waiting. The window is configurable (`PAYMENT_WINDOW_MINUTES`); shorter windows free stock sooner but give customers less time to pay.

---

## 021: Search reads a copy in Elasticsearch, fed by product snapshots

**Decision:** Product search runs against an Elasticsearch index that the search service keeps up to date from `catalog.products`. Each change sends a full snapshot of the product, and its revision is the document version, so the index only ever moves forward to the newest state. PostgreSQL stays the source of truth, and the search service has no database of its own.

**Why:**
- **Search the database can't do well.** Fuzzy full-text matching, facet counts, price ranges across variants and autosuggest run against the index. Running them on the products database would load the service that takes seller edits and serves product pages.
- **Full snapshots keep the consumer simple.** Each message holds everything the index needs, so the search service never calls back to products and never joins anything.
- **The version check handles replays.** Kafka can redeliver and the relay can resend. Elasticsearch refuses any write whose revision isn't newer, so the result is the same however many times a message arrives.
- **Hidden products stay in the index.** A draft or a product with no active option is marked unlisted rather than deleted, so an older listed message can't bring it back.

**Trade-off:** Search lags behind the catalogue, because a change has to pass through the outbox relay and Kafka before the index sees it. Products announced before this change have to be sent once with `python manage.py publish_catalog --once` after deploying it; the command does nothing when products have already been announced. Elasticsearch is one more service to run, and the demo gives it a 512 MB heap.

---

## 022: Storefront search reads the search service, and on-sale stays on the catalogue

**Decision:** The product listing, its facet counts, its sorting and the header's suggestions come from the search service. On-sale browsing, and the listing shown when search is unavailable, still come from the products service, so both keep working.

**Why:**
- **Facets need the index.** Counting colours, sizes and categories across every match is what the search index is built for. The products service would have to scan the catalogue on every page view.
- **Shoppers can still browse when search is down.** The listing falls back to the products service with a notice and without facets, so the shop keeps selling.

**Trade-off:** Search results don't carry discounts yet, because the index doesn't store compare-at prices, so search listings show only the current price. The sale badge appears on the on-sale page, which still reads from the products service. Adding discounts to the index needs a mapping change and a reindex, so that's a later change. Search also lags the catalogue by the time an event takes to pass through the outbox and Kafka.
