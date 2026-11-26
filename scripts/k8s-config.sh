#!/usr/bin/env bash
# Creates what the Kubernetes manifests read, then applies the kind overlay:
#   - the shopverse namespace
#   - Secrets built from the keys in your .env (nothing secret is written into the repo)
#   - the postgres-init ConfigMap from infra/postgres/init
#   - the kind overlay (k8s/overlays/kind)
# Run it again after changing .env: Secrets are replaced in place, and the pods are not restarted.
set -euo pipefail

cd "$(dirname "$0")/.."
NAMESPACE=shopverse
ENV_FILE=${ENV_FILE:-.env}

if [[ ! -f "$ENV_FILE" ]]; then
  echo "No $ENV_FILE. Create it first with: python3 scripts/create_env.py" >&2
  exit 1
fi

# value KEY: the value of KEY in the env file, with one pair of surrounding double quotes removed.
value() {
  local line
  line=$(grep -m1 -E "^$1=" "$ENV_FILE") || { echo "$1 is not set in $ENV_FILE" >&2; exit 1; }
  line=${line#*=}
  line=${line%\"}
  line=${line#\"}
  printf '%s' "$line"
}

# secret NAME KEY...: create or update a Secret holding the listed keys from the env file.
secret() {
  local name=$1
  shift
  local args=()
  local key
  for key in "$@"; do
    args+=(--from-literal="$key=$(value "$key")")
  done
  kubectl -n "$NAMESPACE" create secret generic "$name" "${args[@]}" --dry-run=client -o yaml | kubectl apply -f -
}

kubectl apply -f k8s/base/namespace.yaml

secret shopverse-postgres POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB SERVICE_DATABASES
secret shopverse-redis REDIS_PASSWORD

kubectl -n "$NAMESPACE" create configmap postgres-init --from-file=infra/postgres/init --dry-run=client -o yaml \
  | kubectl apply -f -

kubectl apply -k k8s/overlays/kind
