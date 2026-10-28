#!/bin/bash
# Creates one database per microservice (database-per-service pattern).
# Runs only on the first start of an empty Postgres volume.
set -euo pipefail

if [ -z "${SERVICE_DATABASES:-}" ]; then
  echo "SERVICE_DATABASES is empty, skipping per-service database creation"
  exit 0
fi

for db in $(echo "$SERVICE_DATABASES" | tr ',' ' '); do
  echo "Creating database: $db"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 'CREATE DATABASE "$db"'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$db')\gexec
EOSQL
done
