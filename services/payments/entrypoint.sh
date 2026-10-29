#!/bin/sh
set -e

# Apply database migrations before the web server starts.
# One-off commands such as `pytest` skip this (tests build their own database).
if [ "$1" = "uvicorn" ]; then
  alembic upgrade head
fi

exec "$@"
