#!/bin/sh
set -e

# Apply database migrations before the web server starts.
# One-off commands such as `pytest` skip this (the test runner manages its own database).
if [ "$1" = "gunicorn" ]; then
  python manage.py migrate --noinput
  if [ "$SEED_DEMO_DATA" = "true" ]; then
    python manage.py seed_catalog
  fi
  # Announce variants that existed before catalogue events did (once).
  python manage.py publish_catalog --once
fi

exec "$@"
