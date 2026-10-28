#!/bin/sh
set -e

# Apply database migrations before the web server starts.
# One-off commands such as `pytest` skip this (the test runner manages its own database).
if [ "$1" = "gunicorn" ]; then
  python manage.py migrate --noinput
fi

exec "$@"
