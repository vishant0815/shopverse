#!/usr/bin/env bash
# Creates what the Kubernetes manifests read, then applies the kind overlay:
#   - the shopverse namespace
#   - Secrets built from the keys in your .env (nothing secret is written into the repo)
#   - the shopverse-config ConfigMap: the non-secret settings from your .env
#   - the postgres-init and analytics-schema ConfigMaps from infra/postgres
#   - the kind overlay (k8s/overlays/kind)
# Run it again after changing .env. Secrets and ConfigMaps are replaced in place; pods read them when
# they start, so restart the workloads that use a changed value.
set -euo pipefail

cd "$(dirname "$0")/.."
NAMESPACE=shopverse
ENV_FILE=${ENV_FILE:-.env}

if [[ ! -f "$ENV_FILE" ]]; then
  echo "No $ENV_FILE. Create it first with: python3 scripts/create_env.py" >&2
  exit 1
fi

# value KEY [DEFAULT]: the value of KEY in the env file, with one pair of surrounding double quotes
# removed. Without a DEFAULT, a KEY that is missing from the file is an error.
value() {
  local key=$1 line
  if ! line=$(grep -m1 -E "^$key=" "$ENV_FILE"); then
    if [[ $# -ge 2 ]]; then
      printf '%s' "$2"
      return 0
    fi
    echo "$key is not set in $ENV_FILE" >&2
    return 1
  fi
  line=${line#*=}
  line=${line%\"}
  line=${line#\"}
  printf '%s' "$line"
}

# literal SPEC: sets LITERAL to KEY=VALUE. SPEC is KEY (required) or KEY=DEFAULT (optional).
# Assigning directly, not inside $(...) in the caller, lets a missing required key stop the script.
literal() {
  local spec=$1 key v
  key=${spec%%=*}
  if [[ "$spec" == *=* ]]; then
    v=$(value "$key" "${spec#*=}")
  else
    v=$(value "$key")
  fi
  LITERAL="$key=$v"
}

# secret NAME SPEC...: create or update a Secret from the listed keys.
secret() {
  local name=$1 spec
  local args=()
  shift
  for spec in "$@"; do
    literal "$spec"
    args+=(--from-literal="$LITERAL")
  done
  kubectl -n "$NAMESPACE" create secret generic "$name" "${args[@]}" --dry-run=client -o yaml | kubectl apply -f -
}

# config_map NAME SPEC...: create or update a ConfigMap from the listed keys.
config_map() {
  local name=$1 spec
  local args=()
  shift
  for spec in "$@"; do
    literal "$spec"
    args+=(--from-literal="$LITERAL")
  done
  kubectl -n "$NAMESPACE" create configmap "$name" "${args[@]}" --dry-run=client -o yaml | kubectl apply -f -
}

kubectl apply -f k8s/base/namespace.yaml

secret shopverse-postgres POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB SERVICE_DATABASES
secret shopverse-redis REDIS_PASSWORD
secret shopverse-app JWT_SIGNING_KEY USERS_SECRET_KEY PRODUCTS_SECRET_KEY ORDERS_SECRET_KEY \
  DEMO_USER_PASSWORD= STRIPE_SECRET_KEY= STRIPE_WEBHOOK_SECRET=

config_map shopverse-config \
  DJANGO_DEBUG=false REFRESH_COOKIE_SECURE=false SEED_DEMO_DATA=true PAYMENT_PROVIDER=fake \
  "MAIL_FROM=Shopverse <orders@shopverse.example>" SITE_URL=http://localhost:3002 \
  RATE_LIMIT_DEFAULT=300/minute RATE_LIMIT_LOGIN=10/minute RATE_LIMIT_REFRESH=60/minute \
  RATE_LIMIT_CHECKOUT=10/minute

kubectl -n "$NAMESPACE" create configmap postgres-init --from-file=infra/postgres/init --dry-run=client -o yaml \
  | kubectl apply -f -
kubectl -n "$NAMESPACE" create configmap analytics-schema --from-file=infra/postgres/analytics --dry-run=client -o yaml \
  | kubectl apply -f -

kubectl apply -k k8s/overlays/kind
