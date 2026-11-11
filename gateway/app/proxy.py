"""Forwarding a request to a service and its answer back to the caller."""

import ipaddress
from http.cookiejar import CookieJar, CookiePolicy

import httpx
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import StreamingResponse

# Headers that describe one connection, not the message, and must not be passed on.
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "trailers", "transfer-encoding", "upgrade",
}
# Set by the gateway itself; whatever the caller sent is dropped so it can't be spoofed.
SET_BY_GATEWAY = {
    "host", "content-length", "forwarded", "x-forwarded-for", "x-forwarded-proto",
    "x-forwarded-host", "x-real-ip", "x-request-id",
}


class NoCookies(CookiePolicy):
    """Never keep a cookie, never send one from the jar.

    One HTTP client is shared by every visitor. By default it remembers each Set-Cookie
    it sees and sends it with every later request: one visitor's refresh-token cookie
    would be handed to the next visitor, who'd be signed in as them. Cookies must only
    travel in the visitor's own request and response headers.
    """

    netscape = True
    rfc2965 = False
    hide_cookie2 = True

    def set_ok(self, cookie, request):
        return False

    def return_ok(self, cookie, request):
        return False

    def domain_return_ok(self, domain, request):
        return False

    def path_return_ok(self, path, request):
        return False


def cookie_free_jar() -> CookieJar:
    return CookieJar(policy=NoCookies())


class BodyTooLarge(Exception):
    pass


def client_ip(request: Request, trusted_hops: int) -> str:
    """The caller's address, without trusting anything a client could have made up.

    Every trusted proxy appends the address it saw to X-Forwarded-For, so the entry
    `trusted_hops` from the end was written by our own first proxy. Anything before it
    came from the client and is ignored.
    """
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if trusted_hops == 0 or not forwarded:
        return peer
    parts = [p.strip() for p in forwarded.split(",") if p.strip()]
    if len(parts) < trusted_hops:
        return peer
    candidate = parts[-trusted_hops]
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return peer
    return candidate


async def read_body(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise BodyTooLarge
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise BodyTooLarge
    return bytes(body)


def upstream_headers(request: Request, *, ip: str, request_id: str, trusted_hops: int) -> list[tuple[str, str]]:
    headers = [
        (name, value) for name, value in request.headers.items()
        if name not in HOP_BY_HOP and name not in SET_BY_GATEWAY
    ]
    # A fresh, single-entry X-Forwarded-For: services that read it (the users service's
    # sign-in limit) see the real caller, and nothing a client typed in.
    headers.append(("x-forwarded-for", ip))
    headers.append(("x-request-id", request_id))
    if trusted_hops and request.headers.get("x-forwarded-proto") in ("http", "https"):
        proto = request.headers["x-forwarded-proto"]
    else:
        proto = request.url.scheme
    headers.append(("x-forwarded-proto", proto))
    host = (trusted_hops and request.headers.get("x-forwarded-host")) or request.headers.get("host")
    if host:
        headers.append(("x-forwarded-host", host))
    return headers


# httpx adds these to every request unless told otherwise. The caller's own values (or
# their absence) must win: an Accept-Encoding the browser never sent would get it a
# gzipped body it didn't ask for.
HTTPX_DEFAULTS = ("accept", "accept-encoding", "user-agent")


def build(client: httpx.AsyncClient, method: str, url: str, headers, body: bytes) -> httpx.Request:
    request = client.build_request(method, url, headers=headers, content=body)
    sent = {name for name, _ in headers}
    for name in HTTPX_DEFAULTS:
        if name not in sent and name in request.headers:
            del request.headers[name]
    return request


async def send(client: httpx.AsyncClient, *, method: str, url: str, headers, body: bytes, retry_connect: bool):
    """Send and return the response with its body still unread (streamed back later)."""
    try:
        return await client.send(build(client, method, url, headers, body), stream=True)
    except httpx.ConnectError:
        # Nothing reached the service, so a read can safely be tried once more
        # (it may have just restarted). Writes are never repeated.
        if not retry_connect:
            raise
        return await client.send(build(client, method, url, headers, body), stream=True)


def stream_back(upstream: httpx.Response, request_id: str, extra: dict[str, str]) -> StreamingResponse:
    response = StreamingResponse(upstream.aiter_raw(), status_code=upstream.status_code,
                                 background=BackgroundTask(upstream.aclose))
    # Raw bytes go back untouched (still gzipped if the service gzipped them), so
    # Content-Length and Content-Encoding stay valid. multi_items() keeps every
    # Set-Cookie header instead of folding them into one.
    raw = [
        (name.lower().encode("latin-1"), value.encode("latin-1"))
        for name, value in upstream.headers.multi_items()
        if name.lower() not in HOP_BY_HOP and name.lower() != "x-request-id"
    ]
    raw.append((b"x-request-id", request_id.encode("latin-1")))
    raw.extend((name.lower().encode("latin-1"), value.encode("latin-1")) for name, value in extra.items())
    response.raw_headers = raw
    return response
