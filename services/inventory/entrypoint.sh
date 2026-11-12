#!/bin/sh
set -e

# Apply database migrations before the web server starts.
# The worker and one-off commands such as `pytest` skip this.
if [ "$1" = "uvicorn" ]; then
  alembic upgrade head
fi

exec "$@"
