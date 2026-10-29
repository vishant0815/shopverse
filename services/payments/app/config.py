from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All configuration comes from environment variables."""

    debug: bool = False

    db_name: str = "payments_db"
    db_user: str
    db_password: str
    db_host: str = "localhost"
    db_port: int = 5432

    # Same key the users service signs tokens with.
    jwt_signing_key: str = Field(min_length=1)

    # "fake" needs no Stripe account: payments are completed with a simulate endpoint.
    # "stripe" uses real Stripe test-mode keys.
    payment_provider: Literal["fake", "stripe"] = "fake"
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    orders_service_url: str = "http://localhost:8003"
    orders_service_timeout: float = 5.0

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @model_validator(mode="after")
    def check_secrets(self):
        if not self.debug and len(self.jwt_signing_key) < 32:
            raise ValueError("JWT_SIGNING_KEY must be at least 32 characters")
        if self.payment_provider == "stripe":
            if not self.stripe_secret_key.startswith("sk_test_"):
                # This project only ever takes test payments.
                raise ValueError("STRIPE_SECRET_KEY must be a Stripe test key (sk_test_...)")
            if not self.stripe_webhook_secret.startswith("whsec_"):
                raise ValueError("STRIPE_WEBHOOK_SECRET is required with the stripe provider")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
