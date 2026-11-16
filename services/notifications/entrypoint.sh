#!/bin/sh
set -e

# Apply database migrations before the worker starts.
# One-off commands such as `pytest` skip this (tests build their own database).
if [ "$1" = "python" ]; then
  alembic upgrade head
fi

exec "$@"
