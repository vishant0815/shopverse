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

## 023: Seller approval is announced by event, and products fails closed

**Decision:** Admins approve, suspend and reinstate sellers in the users service. Each change is announced as `SellerStatusChanged` on `users.events`. The products service keeps a copy of each status and refuses a seller's writes unless the seller is approved.

**Why:**
- **Suspensions take effect in seconds.** The products service checks the access token only, and tokens last 15 minutes. Checking the status against a copy kept up to date by events makes a suspension take effect within seconds, not at the next token refresh.
- **It reuses what's already there.** Orders and catalogue changes already go through the outbox and idempotent consumers, so the same pattern carries seller status without a new mechanism.

**Trade-off:** A new seller can't write until their approval status reaches products, a few seconds after registration. Failing closed means that if the products worker is down, seller writes wait rather than letting an unchecked seller in. Suspended sellers' listings stay on the storefront for now, because what happens to a suspended shop's products is a product decision for a later change.

## 024: Coupons are checked at checkout and counted from live orders

**Decision:** Admins create coupon codes in the orders service. A code takes a percentage or a fixed amount off the basket subtotal. The basket checks the code every time it is read, and checkout checks it again under the cart lock. A code's uses aren't stored on the code: they are the orders that carry it and haven't been cancelled.

**Why:**
- **One place for the money.** Checkout already works out the totals and the amount the payment service charges, so the discount is applied there and nowhere else. The order total, the payment and any refund agree without new plumbing.
- **Limits can't be overrun.** The coupon row is locked in the same transaction as the cart, so two checkouts can't both take the last use. Counting from the orders means cancelling an order gives its use back, with no counter to fall out of step.
- **Shipping is judged before the discount.** A coupon never adds a shipping fee to a basket that qualified for free delivery.

**Trade-off:** A usage check reads the orders table. An index on the code keeps that cheap, and it's simpler than a counter that cancellations and expired checkouts would have to keep in step. Coupons apply to the whole basket rather than to particular products or sellers. The platform funds them, so sellers' revenue is unchanged. Flash sales and per-product discounts need their own rules and aren't covered here.

## 025: Flash sales set the price in products and count their caps from live orders

**Decision:** Admins create flash sales in the products service: a time window and chosen variants, each with a sale price below its regular price and an optional unit cap. While a sale runs, the variant lookup returns the sale price as `price`, so carts, checkout and the order snapshot all charge it without special cases. Units sold are counted from live orders by the orders service. Checkout takes a Postgres advisory lock on the sale item before it reads the count, so a capped item can't be oversold. Search shows the sale price, and a scheduled job re-announces a product when one of its sales starts or ends.

**Why:**
- **One price path.** The variant lookup is already the only source of prices for orders, so a sale changes the price in one place and the coupon maths applies on top of it unchanged.
- **Caps can't be overrun.** The advisory lock serialises checkouts for the same sale item, as the coupon row lock does for a code. Counting from live orders means cancelling an order gives its units back.
- **No overlapping prices.** A variant can't be in two sales whose windows overlap, so its price is never ambiguous.

**Trade-off:** Search and the storefront can lag a sale's start or end by up to a minute, the scheduler's interval. A sale that ends between the price lookup and checkout is still charged at its sale price; the client's expected total catches any change. Units sold are read from the orders service, so the product page's "left" count is a snapshot and the cap is enforced only at checkout.

## 026: Reviews are written by verified buyers and kept on the product

**Decision:** Customers review products they have received. The products service accepts a review only when the orders service confirms that a delivered order contains the product. Each customer reviews a product once and can edit that review. The product keeps its average and visible-review count, and search shows them on result cards. Admins hide and show reviews, and a hidden review leaves the page and the rating at once. The orders service answers the purchase check on an internal endpoint that the gateway does not route.

**Why:**
- **Ratings from buyers only.** A review from someone who never received the product is the usual way ratings get gamed, so the check runs on the server against delivered orders, not on anything the storefront sends.
- **One rating, in one place.** Products keeps the average and count on the product row and announces the product to search whenever they change. Search reads the same copy as the rest of the listing, with no extra call per result.
- **Fails closed.** If the orders service can't answer, the review is refused with a retry message rather than accepted unchecked. Seller writes wait for approval in the same way.

**Trade-off:** Writing a review makes one call to the orders service, so it waits on that service. Anyone who can reach the orders service directly can ask whether a user and a product match. The endpoint answers only yes or no and the gateway doesn't route it, so it is reachable only inside the network. Reviews show "Verified purchase" rather than the customer's name, because the sign-in token carries an id and a role, not a name; showing names needs a change in the users service. Reviews publish at once and an admin can hide one afterwards; moderating before publication is not built.

## 027: Customer emails come from a notifications consumer with its own copy of contact details

**Decision:** A notifications worker consumes `orders.events`, `payments.events` and `users.events` and sends the customer emails: order placed, order confirmed, order cancelled, payment failed and refund issued. It keeps its own copy of each customer's name and email, built from `UserRegistered` and `UserContactChanged`, so sending an email never calls the users service. Order events carry the item lines the emails show. No event carries the delivery address; the emails link to the order page for it.

**Why:**
- **No live dependency on users.** An email doesn't need the users service to be up. Products keeps seller status the same way (decision 023).
- **Less personal data in flight.** The address stays on the order, and the customer sees it there, rather than being copied into every event.
- **The service fills the gaps in events.** Payment and cancellation events carry only the order number, so the service keeps an order-to-customer map, recorded from `OrderPlaced`.

**Trade-offs:**
- A send happens inside the message's transaction. A crash after the email leaves but before the commit sends it again on restart. A duplicate is accepted, because a lost order confirmation is worse.
- The topics are read independently, so a customer's first order can arrive before their contact details. Such a message waits up to two minutes, then is dead-lettered.
- Failed sends are not written to `notification_log`. The dead-letter topic records them with the reason, and only sent emails are logged.
- The emails say "within 15 minutes", not a clock time. `OrderPlaced` is sent before stock is held, and no event carries the hold time.
- There is no shipping email yet. The orders service has a shipped status but no event for it, so a shipping email would need one first.

## 028: Storefront events go to Kafka through a collector, and Spark writes Parquet

**Decision:** The storefront sends product views, searches and add-to-cart events to a small collector service, which queues them on `clickstream.events`. A Spark streaming job reads that topic and `orders.events`, drops repeats by event id, and writes raw events, five-minute product totals and search terms to Parquet on a shared volume. Order item lines now carry `product_id`, so purchases can be counted per product.

**Why:**
- **The gateway stays a router.** Ingest has its own service, so it scales and fails on its own, and the gateway doesn't take write traffic it doesn't own today.
- **Analytics doesn't use the outbox.** A lost search event is acceptable. A lost order confirmation is not, so orders keep the outbox and analytics doesn't copy it.
- **Parquet first.** The roadmap items that read these tables (seller analytics, recommendations) can read the files directly, so no database is added before they need one.
- **Event ids make retries safe.** The storefront can resend a batch after a failed request, and Spark counts each event once.

**Trade-offs:**
- "Accepted" means queued in the collector. If the collector process dies before the broker has an event, that event is lost. Analytics accepts this.
- Parquet on one Docker volume is not a warehouse. Spark runs in local mode on one machine; spreading it across machines is a later change.
- Spark's default watermark rule waits for the slowest input, and the orders stream can go quiet for hours. The job uses the `max` policy so windows keep closing. A purchase that arrives more than ten minutes late is left out of the totals.
- Visitors are tied together by an anonymous id in localStorage, not by an IP address. Nothing else about a visitor is collected: no IP address, user agent or full page URLs. The user id comes from the signed-in token, never from the request body.
- The gateway lets clickstream requests through with an expired or broken token, so the collector can record them as anonymous. Every other route still refuses such a token at the gateway.

## 029: Seller analytics are written to Postgres by Spark and read through a seller-only API

**Decision:** The Spark job also reads `catalog.products` to learn which seller owns each product. It writes two tables to an `analytics_db` Postgres database: `product_listings` (one row per product, newest catalogue revision only) and `product_daily` (views, add-to-carts and units sold per product per UTC day). A small `analytics-api` service serves `GET /api/v1/seller/analytics/?days=7|30` to signed-in sellers. Every number it returns is joined to the seller's own listings. The job applies `infra/postgres/analytics/schema.sql` when it starts.

**Why:**
- **The seller comes from the catalogue, never from the event.** A storefront event carries only a product id, so Spark finds the owner in the catalogue's own messages. A shopper can't assign views to someone else's product.
- **Postgres for the seller's reads, Spark for the writes.** The dashboard asks for one seller's products over a date range, which is a filtered lookup. The Parquet files would need a second query engine for that. Postgres is already in the stack.
- **Upserts make replays safe.** Spark may run a batch again after a restart. Replacing a day's totals, and keeping only the newest listing revision, leaves the same numbers.
- **The API checks the role itself.** It verifies the token with the shared key and requires the `seller` role. Sellers and customers are told apart by the service, not the gateway.

**Trade-offs:**
- The job writes to Postgres from its executors, one connection per partition. That is fine at this size. A much larger catalogue would need batching and a connection pool.
- Totals are per UTC day. The dashboard says so.
- The basket rate is add-to-cart events divided by product views. Units sold can't be matched to the view that led to them, so sales are not part of that rate.
- Searches that led to a seller's products are not shown yet. A product view from search doesn't record which query it came from.
- A `503` means the tables don't exist yet, because the job hasn't started. The API doesn't create them itself.
- The `analytics_db` database is created by the Postgres init script only when its volume is empty. On an existing volume it has to be created by hand.

## 030: Frequently bought together is counted by Spark and read through an anonymous API

**Decision:** The Spark job counts how many confirmed orders held each two products. An order's distinct products make pairs, counted in both directions, in a `product_pairs` table in `analytics_db`. The table holds running totals and is rewritten every three minutes. The `analytics-api` service serves `GET /api/v1/recommendations/products/{product_id}/bought-together` without a token. It returns up to three products that share at least two orders with the given one, and the product page shows them.

**Why:**
- **Orders are the unit of counting.** A pair means two products were in the same confirmed order. Confirmed orders are paid ones, so the counts reflect purchases, not carts.
- **Both directions in one table.** One lookup by product id returns its pairs, with an index for the highest counts first. No join and no second query.
- **Running totals are safe to replay.** As with the daily totals (decision 029), each row is replaced by the new count, so a batch run again after a restart leaves the same numbers.
- **Refreshing every few minutes is fresh enough.** Suggestions don't need to change with every order, and a fixed refresh keeps the Postgres writes few and steady.
- **The threshold filters coincidence.** A pair seen in one order is often chance. Requiring two orders keeps the block to products that really sell together.

**Trade-offs:**
- The job keeps a running count for every pair it has seen. The number of pairs grows with the square of the items in each order. That is fine at this size. A larger catalogue would need a time window or a batch job.
- The job reads `orders.events` from the earliest message the topic still holds, so the counts cover whatever the topic retains. Orders older than the retention are not counted.
- A new product has no suggestions until it has sold alongside others, and a bestseller pairs with many products. The rule looks only at orders, not at how often each product sells alone.
- The read is anonymous and cached for two minutes, so shoppers see suggestions a few minutes behind the latest orders.
