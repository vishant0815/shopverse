"""Rate limiting with a token bucket kept in Redis.

Each caller has a bucket of N tokens that refills at N per period. A request takes one
token; an empty bucket means 429. Bursts up to N are fine, a steady flood isn't.

The bucket lives in Redis, not in the gateway's memory, so the limit holds across every
gateway worker and replica. The check-and-take runs as one Lua script, which Redis
executes atomically: two requests arriving together can't both take the last token.
Time comes from Redis's own clock, so gateways with drifting clocks still agree.
"""

import logging
import math
import re
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError

from .auth import Identity
from .config import Settings

log = logging.getLogger("gateway.ratelimit")

PERIODS = {"second": 1, "minute": 60, "hour": 3600}

# KEYS[1] bucket key; ARGV[1] capacity; ARGV[2] refill per second.
# Returns {allowed (1/0), tokens left, seconds until one token is back}.
TOKEN_BUCKET = """
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
local state = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(state[1]) or capacity
local ts = tonumber(state[2]) or now
tokens = math.min(capacity, tokens + math.max(0, now - ts) * rate)
local allowed = 0
local wait = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  wait = (1 - tokens) / rate
end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', KEYS[1], math.ceil(capacity / rate) + 1)
return {allowed, tostring(tokens), tostring(wait)}
"""


@dataclass(frozen=True)
class Rate:
    count: int
    seconds: int

    @classmethod
    def parse(cls, text: str) -> "Rate":
        found = re.fullmatch(r"\s*(\d+)\s*/\s*(second|minute|hour)\s*", text)
        if not found or int(found[1]) < 1:
            raise ValueError(f"Bad rate {text!r}; use e.g. '60/minute'")
        return cls(int(found[1]), PERIODS[found[2]])

    @property
    def per_second(self) -> float:
        return self.count / self.seconds


@dataclass(frozen=True)
class Policy:
    name: str
    rate: Rate
    # "ip": count by address (sign-in attempts, where there's no user yet).
    # "user": count by signed-in user, falling back to address for anonymous callers.
    per: str


@dataclass(frozen=True)
class Decision:
    allowed: bool
    limit: int | None = None
    remaining: int | None = None
    reset_after: int | None = None  # seconds until the bucket is full again
    retry_after: int | None = None  # seconds until the next request would be let in

    def headers(self) -> dict[str, str]:
        if self.limit is None:
            return {}
        headers = {
            "RateLimit-Limit": str(self.limit),
            "RateLimit-Remaining": str(self.remaining),
            "RateLimit-Reset": str(self.reset_after),
        }
        if not self.allowed:
            headers["Retry-After"] = str(self.retry_after)
        return headers


class Policies:
    def __init__(self, settings: Settings):
        self.default = Policy("default", Rate.parse(settings.rate_limit_default), "user")
        self.login = Policy("login", Rate.parse(settings.rate_limit_login), "ip")
        self.refresh = Policy("refresh", Rate.parse(settings.rate_limit_refresh), "ip")
        self.checkout = Policy("checkout", Rate.parse(settings.rate_limit_checkout), "user")

    def for_request(self, method: str, path: str) -> Policy | None:
        if path.startswith("/api/v1/webhooks/"):
            # Signed by Stripe and retried by Stripe; limiting them only delays orders.
            return None
        if method == "POST":
            if path in ("/api/v1/auth/login/", "/api/v1/auth/register/"):
                return self.login
            if path == "/api/v1/auth/refresh/":
                return self.refresh
            if path.startswith("/api/v1/checkout/") or path.rstrip("/") == "/api/v1/payments" \
                    or path.startswith("/api/v1/payments/"):
                return self.checkout
        return self.default


def subject(policy: Policy, identity: Identity | None, client_ip: str) -> str:
    if policy.per == "user" and identity is not None:
        return f"user:{identity.user_id}"
    return f"ip:{client_ip}"


class RateLimiter:
    def __init__(self, redis: Redis):
        self.redis = redis
        self.script = redis.register_script(TOKEN_BUCKET)

    async def hit(self, policy: Policy, who: str) -> Decision:
        rate = policy.rate
        try:
            allowed, tokens, wait = await self.script(keys=[f"rl:{policy.name}:{who}"], args=[rate.count, rate.per_second])
        except RedisError as exc:
            # Fail open: a Redis outage shouldn't take the whole shop down with it.
            # The users service keeps its own sign-in limit as a second line.
            log.warning("rate limiter unavailable, letting request through: %s", exc)
            return Decision(allowed=True)
        tokens = float(tokens)
        return Decision(
            allowed=bool(int(allowed)),
            limit=rate.count,
            remaining=max(0, math.floor(tokens)),
            reset_after=math.ceil((rate.count - tokens) / rate.per_second),
            retry_after=max(1, math.ceil(float(wait))),
        )
