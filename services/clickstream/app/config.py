from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All configuration comes from environment variables."""

    debug: bool = False

    # The same key the users service signs tokens with. Used only to read the user id
    # from a signed-in shopper's token; the collector never trusts a user id in the body.
    jwt_signing_key: str = Field(min_length=1)

    kafka_bootstrap_servers: str = "localhost:9092"
    clickstream_topic: str = "clickstream.events"

    # Events stamped further ahead of this server's clock than this are refused.
    max_clock_skew_seconds: int = 300


@lru_cache
def get_settings() -> Settings:
    return Settings()
