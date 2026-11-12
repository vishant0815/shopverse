from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All configuration comes from environment variables."""

    debug: bool = False

    # Same key the users service signs tokens with; the gateway only verifies.
    jwt_signing_key: str = Field(min_length=1)

    users_service_url: str = "http://localhost:8001"
    products_service_url: str = "http://localhost:8002"
    orders_service_url: str = "http://localhost:8003"
    payments_service_url: str = "http://localhost:8004"
    inventory_service_url: str = "http://localhost:8005"
    # Everything that isn't /api/... (pages, scripts, images) goes to the storefront.
    storefront_url: str = "http://localhost:3000"

    # Seconds. Connecting should be near-instant on the internal network; reads get longer.
    upstream_connect_timeout: float = 2.0
    upstream_read_timeout: float = 15.0

    # Requests bigger than this are refused before they reach a service.
    max_body_bytes: int = 1_048_576

    # How many proxies in front of the gateway add the caller's address to X-Forwarded-For.
    # 0 = browsers connect straight to the gateway (use the socket address; any
    # X-Forwarded-For they send is ignored). Behind a cloud load balancer, set 1.
    trusted_proxy_hops: int = 0

    redis_url: str = "redis://localhost:6379/2"
    rate_limit_enabled: bool = True
    # "<count>/<second|minute|hour>". See ratelimit.py for which requests each one covers.
    rate_limit_default: str = "300/minute"
    rate_limit_login: str = "10/minute"
    rate_limit_refresh: str = "60/minute"
    rate_limit_checkout: str = "10/minute"

    # Circuit breaker: after this many failures in a row, stop calling a service for a while.
    breaker_failure_threshold: int = 5
    breaker_reset_seconds: float = 15.0

    @model_validator(mode="after")
    def check(self):
        if not self.debug and len(self.jwt_signing_key) < 32:
            raise ValueError("JWT_SIGNING_KEY must be at least 32 characters")
        if self.trusted_proxy_hops < 0:
            raise ValueError("TRUSTED_PROXY_HOPS can't be negative")
        return self

    @property
    def upstreams(self) -> dict[str, str]:
        return {
            "users": self.users_service_url.rstrip("/"),
            "products": self.products_service_url.rstrip("/"),
            "orders": self.orders_service_url.rstrip("/"),
            "payments": self.payments_service_url.rstrip("/"),
            "inventory": self.inventory_service_url.rstrip("/"),
            "storefront": self.storefront_url.rstrip("/"),
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
