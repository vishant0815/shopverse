# Kubernetes manifests

The manifests run Shopverse's shared infrastructure on a local [kind](https://kind.sigs.k8s.io/) cluster: PostgreSQL, Redis and Kafka. The services follow in a later change.

## Layout

```
k8s/
├── kind-cluster.yaml        # the local cluster (one node)
├── base/                    # what every environment runs
│   ├── namespace.yaml       # the shopverse namespace
│   ├── postgres.yaml        # StatefulSet with a 2 GiB volume
│   ├── redis.yaml           # StatefulSet with password auth and AOF
│   └── kafka.yaml           # one KRaft broker, headless Service
└── overlays/kind/           # the local cluster's settings (applied by scripts/k8s-config.sh)
```

## Running it

You need Docker, [kind](https://kind.sigs.k8s.io/) and kubectl.

```bash
# 1. A cluster
kind create cluster --name shopverse --config k8s/kind-cluster.yaml

# 2. Secrets, the init ConfigMap and the manifests. Reads keys from your .env.
scripts/k8s-config.sh

# 3. Wait for the three StatefulSets
kubectl -n shopverse rollout status statefulset/postgres
kubectl -n shopverse rollout status statefulset/redis
kubectl -n shopverse rollout status statefulset/kafka
```

Inside the cluster, services reach these at `postgres:5432`, `redis:6379` and `kafka:9092`, the same names docker-compose uses.

## Secrets

`scripts/k8s-config.sh` builds the Secrets from your local `.env`, so no secret value is committed:

| Secret | Keys |
|---|---|
| `shopverse-postgres` | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `SERVICE_DATABASES` |
| `shopverse-redis` | `REDIS_PASSWORD` |

Run the script again after changing `.env`. It replaces the Secrets in place. Pods read Secrets when they start, so restart a StatefulSet to pick up a new value: `kubectl -n shopverse rollout restart statefulset/<name>`.

## Scope and limits

- One replica of each component, with local-path storage from kind. A real cluster needs three or more Kafka brokers and a replicated PostgreSQL.
- Postgres and Redis are not reachable from outside the cluster. Use `kubectl port-forward` to look at them.
- Services, the gateway and the storefront are not in these manifests yet.
