"""Shopverse API gateway: the one door every browser request comes through.

/api/... requests go to the services. For each one, in this order:
 1. give it a request id (kept if the caller sent a sane one), echoed in the response
    and passed to the service, so one request can be followed across logs;
 2. find the service from the path; unknown paths (including services' internal
    endpoints) stop here with 404;
 3. refuse bodies over the size limit;
 4. check the access token, if there is one;
 5. take a token from the caller's rate-limit bucket;
 6. refuse a bad token (after step 5, so guessing tokens is rate limited too);
 7. skip services whose circuit breaker is open;
 8. forward, stream the answer back, and log one JSON line.

Everything else (pages, scripts, images) goes to the storefront with steps 1, 3, 7
and 8 only. Serving the whole site from here is what lets the gateway see each
visitor's real address, which per-address rate limits depend on.
"""

import asyncio
import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from redis.asyncio import Redis
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import proxy
from .auth import BadToken, identify
from .breaker import Breakers
from .config import Settings, get_settings
from .ratelimit import Policies, RateLimiter, subject
from .routes import match

logging.basicConfig(level=logging.INFO, format="%(message)s")
# httpx logs every upstream call at INFO; the access log below already covers each request.
logging.getLogger("httpx").setLevel(logging.WARNING)
access_log = logging.getLogger("gateway.access")
log = logging.getLogger("gateway")

METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{8,64}")
HEALTH_PATHS = {"users": "/health/", "products": "/health/", "orders": "/health/", "payments": "/health",
                "inventory": "/health", "storefront": "/favicon.svg"}
# Fingerprinted build files: many per page load and never interesting in the log.
QUIET_PATHS = ("/_next/static/", "/favicon.svg")


def error(status: int, detail: str, code: str, request_id: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse({"detail": detail, "code": code}, status_code=status,
                        headers={"X-Request-ID": request_id, **(headers or {})})


def create_app(settings: Settings | None = None, *, transport: httpx.AsyncBaseTransport | None = None,
               clock=time.monotonic) -> FastAPI:
    """`transport` and `clock` let tests stand in for the services and for time."""
    settings = settings or get_settings()
    policies = Policies(settings)  # fails fast on a badly written rate

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        timeout = httpx.Timeout(settings.upstream_read_timeout, connect=settings.upstream_connect_timeout)
        limits = httpx.Limits(max_connections=200, max_keepalive_connections=50)
        app.state.client = httpx.AsyncClient(transport=transport, timeout=timeout, limits=limits,
                                             follow_redirects=False, cookies=proxy.cookie_free_jar())
        app.state.redis = Redis.from_url(settings.redis_url, socket_timeout=0.5, socket_connect_timeout=0.5)
        app.state.limiter = RateLimiter(app.state.redis)
        app.state.breakers = Breakers(settings.breaker_failure_threshold, settings.breaker_reset_seconds, clock)
        yield
        await app.state.client.aclose()
        await app.state.redis.aclose()

    # No /docs: the gateway has no API of its own, and each service documents its own.
    app = FastAPI(title="Shopverse API gateway", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def request_id_and_log(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        request.state.request_id = incoming if REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex
        request.state.log = {}
        started = time.perf_counter()
        response = await call_next(request)
        response.headers.setdefault("X-Request-ID", request.state.request_id)
        if not request.url.path.startswith(QUIET_PATHS):
            access_log.info(json.dumps({
                "request_id": request.state.request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "ms": round((time.perf_counter() - started) * 1000, 1),
                **request.state.log,
            }))
        return response

    @app.get("/health", include_in_schema=False)
    async def health():
        return {"status": "ok", "service": "gateway"}

    @app.get("/health/ready", include_in_schema=False)
    async def ready(request: Request):
        """Can the gateway do its job: is Redis there, and is every service answering?"""
        client: httpx.AsyncClient = request.app.state.client

        async def check_service(name: str, base: str) -> str:
            try:
                answer = await client.get(base + HEALTH_PATHS[name], timeout=2.0)
                return "ok" if answer.status_code == 200 else f"status {answer.status_code}"
            except httpx.HTTPError:
                return "unreachable"

        async def check_redis() -> str:
            try:
                await request.app.state.redis.ping()
                return "ok"
            except Exception:
                return "unreachable"

        names = list(settings.upstreams)
        results = await asyncio.gather(check_redis(), *(check_service(n, settings.upstreams[n]) for n in names))
        checks = {"redis": results[0], **dict(zip(names, results[1:]))}
        healthy = all(value == "ok" for value in checks.values())
        return JSONResponse(
            {"status": "ok" if healthy else "degraded", "checks": checks,
             "breakers": request.app.state.breakers.states()},
            status_code=200 if healthy else 503,
        )

    async def pass_on(request: Request, service: str, target: str, body: bytes, ip: str,
                      extra_headers: dict[str, str]):
        rid = request.state.request_id
        breaker = request.app.state.breakers[service]
        if not breaker.allow():
            return error(503, f"The {service} service is temporarily unavailable. Try again shortly.",
                         "service_unavailable", rid, {"Retry-After": str(breaker.retry_after())})

        url = settings.upstreams[service] + target
        if request.url.query:
            url += "?" + request.url.query
        headers = proxy.upstream_headers(request, ip=ip, request_id=rid, trusted_hops=settings.trusted_proxy_hops)
        try:
            upstream = await proxy.send(request.app.state.client, method=request.method, url=url, headers=headers,
                                        body=body, retry_connect=request.method in ("GET", "HEAD"))
        except httpx.TimeoutException:
            breaker.failure()
            log.warning(json.dumps({"request_id": rid, "event": "upstream_timeout", "service": service}))
            return error(504, f"The {service} service took too long to answer.", "gateway_timeout", rid)
        except httpx.TransportError:
            breaker.failure()
            log.warning(json.dumps({"request_id": rid, "event": "upstream_unreachable", "service": service}))
            return error(502, f"The {service} service could not be reached.", "bad_gateway", rid)
        breaker.success()
        return proxy.stream_back(upstream, rid, extra_headers)

    @app.api_route("/api/{rest:path}", methods=METHODS, include_in_schema=False)
    async def api(request: Request):
        rid = request.state.request_id
        path = request.url.path
        route = match(path)
        if route is None:
            return error(404, "Not found.", "not_found", rid)
        request.state.log["service"] = route.service

        try:
            body = await proxy.read_body(request, settings.max_body_bytes)
        except proxy.BodyTooLarge:
            return error(413, "Request body is too large.", "too_large", rid)

        ip = proxy.client_ip(request, settings.trusted_proxy_hops)
        request.state.log["ip"] = ip
        try:
            identity, token_problem = identify(request.headers.get("authorization")), None
        except BadToken as exc:
            identity, token_problem = None, str(exc)
        if identity:
            request.state.log["user"] = identity.user_id

        limit_headers = {}
        policy = policies.for_request(request.method, path) if settings.rate_limit_enabled else None
        if policy:
            decision = await request.app.state.limiter.hit(policy, subject(policy, identity, ip))
            limit_headers = decision.headers()
            request.state.log["limit"] = policy.name
            if not decision.allowed:
                wait = decision.retry_after
                return error(429, f"Too many requests. Try again in {wait} second{'s' if wait != 1 else ''}.",
                             "rate_limited", rid, limit_headers)

        if token_problem:
            return error(401, token_problem, "token_not_valid", rid, {"WWW-Authenticate": "Bearer", **limit_headers})

        return await pass_on(request, route.service, route.rewrite_to or path, body, ip, limit_headers)

    @app.api_route("/{rest:path}", methods=METHODS, include_in_schema=False)
    async def site(request: Request):
        try:
            body = await proxy.read_body(request, settings.max_body_bytes)
        except proxy.BodyTooLarge:
            return error(413, "Request body is too large.", "too_large", request.state.request_id)
        ip = proxy.client_ip(request, settings.trusted_proxy_hops)
        request.state.log.update(service="storefront", ip=ip)
        return await pass_on(request, "storefront", request.url.path, body, ip, {})

    return app


app = create_app()
