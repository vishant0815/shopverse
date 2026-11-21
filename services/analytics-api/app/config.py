from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All configuration comes from environment variables."""

    debug: bool = False

    # The same key the users service signs tokens with. This service only verifies them.
    jwt_signing_key: str = Field(min_length=1)

    # The analytics database, written by the Spark job (see analytics/clickstream/postgres.py).
    database_url: str = Field(min_length=1)

    @model_validator(mode="after")
    def check(self):
        if not self.debug and len(self.jwt_signing_key) < 32:
            raise ValueError("JWT_SIGNING_KEY must be at least 32 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
