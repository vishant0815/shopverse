from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    es_url: str = "http://localhost:9200"
    search_index: str = "products"

    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_group: str = "search"
    products_topic: str = "catalog.products"


@lru_cache
def get_settings() -> Settings:
    return Settings()
