# Product service

The catalogue for Shopverse: categories, products, variants and images. Customers browse and filter it; sellers manage their own listings; admins manage categories and can moderate any product.

**Stack:** Django 5.1, Django REST Framework, django-filter, PostgreSQL (`products_db`), Redis (category cache)

## Data model

```
Category (tree: Electronics > Mobiles)
  └── Product (seller_id, name, slug, brand, status: draft | active | archived)
        ├── ProductVariant (sku, colour, size, price, compare_at_price)
        └── ProductImage (url, alt_text, position)
```

- **Prices live on variants,** because "Blue, M" and "Black, L" can cost different amounts. Product listings show the lowest active variant price.
- **Stock is not stored here.** It will belong to the inventory service, keyed by SKU.
- **`seller_id`** is the seller's id from the users service. There is no foreign key across services (database per service).
- Images are stored as URLs, ready for object storage such as S3.

## Authentication

This service does not store users. It verifies JWTs issued by the users service using the shared `JWT_SIGNING_KEY` and reads two claims: `user_id` and `role`. No call to the users service is needed per request.

## API

Base path: `/api/v1/`

### Storefront (public)

| Method | Endpoint | Description |
|---|---|---|
| GET | `products/` | Published products, paginated |
| GET | `products/{slug}/` | Product detail with active variants and images |
| GET | `categories/` | Active categories (flat list) |
| GET | `categories/tree/` | Active categories as a nested tree, cached in Redis |

**Filters on `products/`:**

| Parameter | Example | Notes |
|---|---|---|
| `category` | `electronics` | Includes all subcategories |
| `brand` | `nova,aero` | One or more, case-insensitive |
| `min_price`, `max_price` | `50`, `500` | Based on the lowest variant price |
| `colour`, `size` | `blue`, `M` | Matches any active variant |
| `search` | `wireless` | Name, brand and description |
| `ordering` | `min_price`, `-min_price`, `-created_at`, `name` | |
| `page`, `page_size` | `2`, `24` | Max 100 per page |

```bash
curl "http://localhost:8002/api/v1/products/?category=fashion&colour=blue&ordering=min_price"
```

### Seller (role `seller` or `admin`)

| Method | Endpoint | Description |
|---|---|---|
| GET / POST | `seller/products/` | Your products (drafts included); create a product, optionally with variants and images |
| GET / PATCH / DELETE | `seller/products/{id}/` | Manage one product; DELETE archives it |
| GET / POST | `seller/products/{id}/variants/` | List or add variants |
| PATCH / DELETE | `seller/products/{id}/variants/{variant_id}/` | Update or deactivate a variant |
| GET / POST | `seller/products/{id}/images/` | List or add images |
| PATCH / DELETE | `seller/products/{id}/images/{image_id}/` | Update or remove an image |

Example: create and publish a product in one request.

```bash
curl -H "Authorization: Bearer <seller access token>" -H "Content-Type: application/json" \
  -d '{
        "name": "Nova X1", "brand": "Nova", "category": "mobiles", "status": "active",
        "variants": [{"sku": "NOVA-X1-BLK", "colour": "Black", "size": "128GB", "price": "399.00", "compare_at_price": "449.00"}],
        "images": [{"url": "https://example.com/nova.jpg", "alt_text": "Nova X1"}]
      }' \
  http://localhost:8002/api/v1/seller/products/
```

### Admin (role `admin`)

| Method | Endpoint | Description |
|---|---|---|
| POST | `categories/` | Create a category (`parent` is a slug) |
| PATCH / DELETE | `categories/{slug}/` | Update or deactivate a category |

Admins can also use every seller endpoint on any product.

## Rules enforced

- A product can only be **published** if it has at least one active variant; deactivating the last variant moves it back to draft.
- **Prices** must be positive, and `compare_at_price` can't be lower than `price` (checked in the API and by database constraints).
- **SKUs** are unique and stored in upper case; a product can't have two variants with the same colour and size.
- **Nothing is hard-deleted:** products are archived, variants and categories deactivated, so past orders still make sense.
- A category can't be moved under one of its own subcategories.

## Security

- **Role checks** from the verified JWT: only sellers and admins reach seller endpoints, only admins change categories.
- **Ownership:** a seller's queries are always filtered by their own `seller_id`, so another seller's product returns 404. The `seller_id` on a new product comes from the token, never the request body.
- **Forged or expired tokens** fail signature or expiry checks and get 401.
- Image URLs are validated as `http`/`https` URLs.

## Performance

- Product lists load in a fixed number of queries however many products are returned (select_related, prefetch_related and a `Min` price annotation). A test guards against N+1 queries.
- Colour and size filters use `EXISTS` subqueries rather than joins, so products aren't duplicated and prices stay correct.
- Database indexes on status, category, creation date and brand.
- The category tree is cached in Redis and cleared automatically when any category changes.

## Running

```bash
docker compose up -d products        # also starts Postgres and Redis
```

The API is on http://localhost:8002. With `SEED_DEMO_DATA=true` (the default in `.env.example`) the service loads 11 categories and 12 demo products on start. To load them manually:

```bash
docker compose exec products python manage.py seed_catalog          # safe to run again
docker compose exec products python manage.py seed_catalog --reset  # recreate demo products
```

## Tests

```bash
docker compose run --rm products pytest
```

50 tests cover browsing, every filter, sorting, pagination, N+1 protection, category caching, role checks, ownership, validation rules and forged tokens.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DJANGO_SECRET_KEY` | required | |
| `JWT_SIGNING_KEY` | required | Same value as the users service; at least 32 characters outside debug |
| `DJANGO_DEBUG` | `false` | |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | `products_db`, required, required, `localhost`, `5432` | |
| `REDIS_URL` | unset (in-memory cache) | |
| `CATEGORY_CACHE_SECONDS` | `300` | How long the category tree is cached |
| `SEED_DEMO_DATA` | unset | `true` loads demo data on start |
