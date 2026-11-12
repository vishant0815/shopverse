from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All configuration comes from environment variables."""

    debug: bool = False

    db_name: str = "inventory_db"
    db_user: str
    db_password: str
    db_host: str = "localhost"
    db_port: int = 5432

    # Same key the users service signs tokens with; this service only verifies.
    jwt_signing_key: str = Field(min_length=1)

    kafka_bootstrap_servers: str = "localhost:9092"

    # Demo only: give each new variant some stock (a few sold out, a few running low),
    # so the seeded shop is buyable without a seller filling in every number.
    demo_stock: bool = False

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
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
