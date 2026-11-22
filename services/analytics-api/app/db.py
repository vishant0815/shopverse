"""Database connections for the analytics API."""

from collections.abc import Iterator

import psycopg

from .config import get_settings


def get_connection() -> Iterator[psycopg.Connection]:
    # Reads only, so each statement commits by itself and nothing is held open between requests.
    conn = psycopg.connect(get_settings().database_url, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()
