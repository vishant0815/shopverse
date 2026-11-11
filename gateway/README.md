# API gateway

The single entry point for the whole site. Browsers only ever talk to the gateway: it sends pages, scripts and images to the storefront, and `/api/...` requests to the right service after checking the access token and the caller's rate limit.

Built with **FastAPI**, **httpx** (async, streaming) and **Redis**.

```
browser ──► gateway ──► storefront         pages, scripts, images
               │
               ├──► users                  /api/v1/auth/, users/, addresses/
               ├──► products               /api/v1/products/, categories/, variants/, seller/products/
               ├──► orders                 /api/v1/cart/, checkout/, orders/, seller/sales/, seller/summary/, admin/
               ├──► payments               /api/v1/payments/, webhooks/
               └──► Redis                  rate-limit buckets
```

## What it does with each API request

1. **Request id.** Every request gets an `X-Request-ID` (a sane one sent by the caller is kept). It goes to the service and comes back in the response, so one request can be followed through every log.
2. **Routing.** The longest matching path prefix picks the service; the path is passed on unchanged. Paths that match nothing get a 404 here. That includes the services' internal endpoints (such as `/api/v1/internal/...`, which payments uses to tell orders an order is paid), so they can't be reached from outside.
3. **Body size.** Bodies over 1 MiB are refused with 413 before they reach a service.
4. **Token check.** A missing token is fine (services decide what anonymous callers may do). A bad, expired, unsigned or refresh token is refused with 401 at the door, the same answer the services give, so the storefront's refresh-and-retry works the same way. The services still check roles themselves.
5. **Rate limit.** See below. Bad-token requests are counted too, so guessing tokens is limited.
6. **Circuit breaker.** See below.
7. **Forwarding.** The answer is streamed back byte for byte: compressed bodies stay compressed, and every `Set-Cookie` header is kept separate.
8. **Access log.** One JSON line per request: request id, method, path, status, time taken, service, caller address, user id and which rate limit applied.

## Rate limits

A **token bucket per caller, kept in Redis.** Each caller has a bucket of N tokens that refills at N per period, and each request takes one. Short bursts are fine; a steady flood gets 429.

| Limit | Applies to | Counted per | Default |
|---|---|---|---|
| `login` | `POST auth/login/`, `auth/register/` | address | 10 / minute |
| `refresh` | `POST auth/refresh/` (once per page load) | address | 60 / minute |
| `checkout` | `POST checkout/`, `payments` | user (or address) | 10 / minute |
| `default` | every other API request | user (or address) | 300 / minute |

Stripe webhooks aren't limited: they're signed, and Stripe retries them anyway. Pages aren't limited either; flooding them is a job for a CDN in front.

Every limited response carries `RateLimit-Limit`, `RateLimit-Remaining` and `RateLimit-Reset` headers. A refused request gets 429, `Retry-After`, and `{"detail": "Too many requests. Try again in 20 seconds.", "code": "rate_limited"}`.

How it's built:

- **One Lua script does the check and the take.** Redis runs it atomically, so two requests arriving together can't both take the last token. A test fires 50 requests at once at a bucket of 10, and exactly 10 get through.
- **Redis's clock, not the gateway's.** Several gateways with slightly different clocks still agree.
- **Shared across workers and replicas,** because the buckets live in Redis rather than in memory.
- **Signed-in users are counted by account,** so people sharing an office or a mobile network don't use up each other's allowance.
- **Fails open.** If Redis is down, requests go through without limits (and a warning is logged) rather than the whole shop going down with Redis. The users service keeps its own sign-in limit as a second line.

## Callers' real addresses

Per-address limits are only worth something if a client can't pick its own address. The gateway works out the caller's address from the connection itself. It only reads `X-Forwarded-For` when `TRUSTED_PROXY_HOPS` says a known proxy is in front, and then only the entry that proxy wrote. Anything a client typed into the header is ignored.

It then sends the services a fresh, single-entry `X-Forwarded-For` containing just that address. The users service (`NUM_PROXIES=1`) uses it for its own limits.

This is why the gateway serves the pages too. With the storefront in front, the gateway would only ever see the storefront's address. Next.js passes on whatever `X-Forwarded-For` the browser sent, so a client could also make one up.

## Circuit breaker

When a service stops answering, every request to it would otherwise wait for the full timeout and pile more load onto a service that's already struggling. After 5 failures in a row (refused connections or timeouts; a 500 is still an answer), requests to that service get an immediate 503 with `Retry-After` for 15 seconds. Then one trial request is let through: if it works, traffic resumes, and if not, the breaker opens again. Each service has its own breaker, so one being down doesn't affect the rest.

Other failures: a service that can't be reached gives 502, and one that's too slow gives 504. Reads (`GET`/`HEAD`) are retried once if the connection itself failed, since nothing reached the service. Writes are never retried.

## Endpoints of its own

| Path | Purpose |
|---|---|
| `GET /health` | The gateway is running (used by the Docker health check) |
| `GET /health/ready` | Redis and every service are answering; 503 with details if not, plus each breaker's state |

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `JWT_SIGNING_KEY` | (required) | Same key the users service signs tokens with |
| `REDIS_URL` | `redis://localhost:6379/2` | Where the rate-limit buckets live |
| `USERS_SERVICE_URL`, `PRODUCTS_SERVICE_URL`, `ORDERS_SERVICE_URL`, `PAYMENTS_SERVICE_URL`, `STOREFRONT_URL` | `localhost:8001`–`8004`, `3000` | Where each upstream runs |
| `TRUSTED_PROXY_HOPS` | `0` | Proxies in front that append to `X-Forwarded-For` (set `1` behind a cloud load balancer) |
| `RATE_LIMIT_DEFAULT`, `RATE_LIMIT_LOGIN`, `RATE_LIMIT_REFRESH`, `RATE_LIMIT_CHECKOUT` | see table above | `<count>/<second\|minute\|hour>`; a badly written one stops the gateway starting |
| `RATE_LIMIT_ENABLED` | `true` | Switch limits off (for load tests) |
| `UPSTREAM_CONNECT_TIMEOUT`, `UPSTREAM_READ_TIMEOUT` | `2`, `15` seconds | |
| `MAX_BODY_BYTES` | `1048576` | |
| `BREAKER_FAILURE_THRESHOLD`, `BREAKER_RESET_SECONDS` | `5`, `15` | |

## Cost

Measured locally over 150 sequential requests for a page of 12 products: **p50 11.7 ms direct, 15.5 ms through the gateway** (p95 15.5 → 18.6 ms). That's about 4 ms for routing, the token check, a Redis round trip and the extra hop.

## Tests

```bash
docker compose run --rm gateway pytest    # 92 tests
```

The services are replaced by an in-process fake (httpx `MockTransport`) that streams its answers like a real socket, and the rate limits run against a real Redis (database 15, emptied around each test). The tests cover:

- routing for every prefix, and that internal and unknown paths stop at the gateway
- header handling: hop-by-hop headers, spoofed addresses, request ids, compressed bodies, multiple cookies
- every kind of bad token
- each rate limit: refill over time, Redis down, and the 50-at-once race
- the breaker's open, half-open and closed states
- readiness, and page traffic to the storefront

One test makes sure **a cookie set for one visitor is never sent with another visitor's request.** httpx clients keep a cookie jar by default, and a shared client would have handed one person's refresh token to the next person. The gateway's client uses a jar that refuses every cookie.
