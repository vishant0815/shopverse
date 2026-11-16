from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All configuration comes from environment variables."""

    db_name: str = "notifications_db"
    db_user: str
    db_password: str
    db_host: str = "localhost"
    db_port: int = 5432

    kafka_bootstrap_servers: str = "localhost:9092"

    # SMTP. Development uses Mailpit (no login, no TLS); production uses a real relay.
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = False
    mail_from: str = "Shopverse <orders@shopverse.example>"

    # Links in the emails point at the storefront.
    site_url: str = "http://localhost:3002"

    # The checkout hold, in minutes. Must match the orders service (its default is 15).
    payment_window_minutes: int = 15

    # How long a message waits for a customer's contact details before it is dead-lettered.
    # users.events and orders.events are separate topics, so a first order can arrive first.
    recipient_wait_seconds: float = 120.0

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
