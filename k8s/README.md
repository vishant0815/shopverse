# Kubernetes manifests

The manifests run Shopverse on a local [kind](https://kind.sigs.k8s.io/) cluster: the shared infrastructure (PostgreSQL, Redis, Kafka, Elasticsearch) and the application (the API services and their workers, the gateway, the storefront, the analytics job and the notifications worker).

## Layout

```
k8s/
├── kind-cluster.yaml        # the local cluster (one node)
├── base/                    # what every environment runs
│   ├── namespace.yaml       # the shopverse namespace
│   ├── postgres.yaml        # StatefulSet with a 2 GiB volume
│   ├── redis.yaml           # StatefulSet with password auth and AOF
│   ├── kafka.yaml           # one KRaft broker, headless Service
│   └── services/            # the application, one file per service (see below)
└── overlays/kind/           # the local cluster's settings (applied by scripts/k8s-config.sh)
```

`services/` mirrors `docker-compose.yml`: each service runs the image built from its folder, and its workers run the same image with a different command. Services find each other by the same names compose uses (`users`, `orders`, `gateway`, ...).

| File | Runs |
|---|---|
| `users.yaml`, `products.yaml`, `orders.yaml`, `inventory.yaml` | Django and FastAPI services, with their workers and the products flash-sale scheduler |
| `payments.yaml` | the payments service and its worker (Stripe or the fake provider) |
| `search.yaml` | the search service, its Kafka consumer, and a single-node Elasticsearch |
| `clickstream.yaml` | the service that accepts storefront events and queues them on Kafka |
| `analytics.yaml` | the seller-dashboard API and the Spark job, which writes to a 2 GiB volume |
| `gateway.yaml` | the gateway, the only entry point from outside the cluster |
| `storefront.yaml` | the Next.js storefront |
| `notifications.yaml` | the notifications worker and Mailpit, a development mail catcher |

## Running it

You need Docker, [kind](https://kind.sigs.k8s.io/) and kubectl. The application images are pulled from GitHub Container Registry (`ghcr.io/vishant0815/shopverse-*`), so they must be published before the pods can start.

```bash
# 1. A cluster
kind create cluster --name shopverse --config k8s/kind-cluster.yaml

# 2. Secrets, ConfigMaps and the manifests. Reads keys from your .env.
scripts/k8s-config.sh

# 3. Wait for the infrastructure
kubectl -n shopverse rollout status statefulset/postgres
kubectl -n shopverse rollout status statefulset/redis
kubectl -n shopverse rollout status statefulset/kafka
kubectl -n shopverse rollout status statefulset/elasticsearch

# 4. Open the site at http://localhost:3000 (the gateway serves the storefront and the API)
kubectl -n shopverse port-forward svc/gateway 3000:8000
```

Inside the cluster, services reach each other at the names in the table above, plus `postgres:5432`, `redis:6379`, `kafka:9092` and `elasticsearch:9200`.

Nothing waits for its dependencies: a pod that starts before Postgres or Kafka is ready exits and Kubernetes restarts it. Expect some `CrashLoopBackOff` in the first minute or two, and it clears on its own.

## Secrets and ConfigMaps

`scripts/k8s-config.sh` builds these from your local `.env`, so no value is committed:

| Object | Kind | Keys |
|---|---|---|
| `shopverse-postgres` | Secret | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `SERVICE_DATABASES` |
| `shopverse-redis` | Secret | `REDIS_PASSWORD` |
| `shopverse-app` | Secret | `JWT_SIGNING_KEY`, `USERS_SECRET_KEY`, `PRODUCTS_SECRET_KEY`, `ORDERS_SECRET_KEY`, `DEMO_USER_PASSWORD`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` |
| `shopverse-config` | ConfigMap | `DJANGO_DEBUG`, `REFRESH_COOKIE_SECURE`, `SEED_DEMO_DATA`, `PAYMENT_PROVIDER`, `MAIL_FROM`, `SITE_URL`, `RATE_LIMIT_*` |
| `postgres-init` | ConfigMap | the files in `infra/postgres/init` |
| `analytics-schema` | ConfigMap | the files in `infra/postgres/analytics` |

The script stops with a message if a required key is missing from `.env`. Keys with a default (`DJANGO_DEBUG`, `PAYMENT_PROVIDER`, the rate limits and the like) use the same defaults as docker-compose when they are absent.

Run the script again after changing `.env`. It replaces the objects in place. Pods read their values when they start, so restart what uses a changed value, for example `kubectl -n shopverse rollout restart deployment/payments`.

## Scope and limits

- One replica of each component, with local-path storage from kind. A real cluster needs three or more Kafka brokers, a replicated PostgreSQL and a replicated Elasticsearch.
- Elasticsearch needs the host kernel setting `vm.max_map_count` of at least 262144. Without it, the pod usually exits at start-up.
- The memory needs have not been measured. Elasticsearch and the Spark job request the most, so check `kubectl describe node` for the allocated requests once everything is running.
- The storefront's `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` is built into the image, not read at run time, so the image must be built with it.
- Mailpit keeps mail in memory and delivers nothing outside the cluster. Point `MAIL_FROM` and the notifications worker at a real SMTP host before running anywhere else.
- Only the gateway is reachable from outside the cluster. Postgres, Redis and Kafka are not. Use `kubectl port-forward` to look at them.
- Not checked against a live cluster yet. The manifests render with `kubectl kustomize`, and the script's logic is tested with a stub `kubectl`.
