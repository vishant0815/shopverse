# Users service

Handles accounts and identity for Shopverse: registration, login, JWT tokens, profiles, roles and saved addresses.

**Stack:** Django 5.1, Django REST Framework, Simple JWT, PostgreSQL (`users_db`), Redis (rate-limit counters)

## API

Base path: `/api/v1/`

### Auth

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `auth/register/` | Public | Create an account (`customer` or `seller`) and log in |
| POST | `auth/login/` | Public | Log in with email and password |
| POST | `auth/refresh/` | Refresh cookie | Get a new access token; rotates the refresh token |
| POST | `auth/logout/` | Refresh cookie | Revoke the refresh token and clear the cookie |

Login and register return the **access token** in the JSON body and set the **refresh token** as an `httpOnly` cookie scoped to `/api/v1/auth/`. Send the access token on other requests as:

```
Authorization: Bearer <access token>
```

Access tokens last 15 minutes and refresh tokens 7 days (configurable). Both carry a `role` claim so other services can authorise without calling this one.

### Profile

| Method | Endpoint | Description |
|---|---|---|
| GET | `users/me/` | Current user's profile |
| PATCH | `users/me/` | Update name and phone (email and role are read-only) |
| POST | `users/me/change-password/` | Change password; ends the current refresh session |

### Addresses

| Method | Endpoint | Description |
|---|---|---|
| GET | `addresses/` | List own addresses (paginated, default first) |
| POST | `addresses/` | Add an address |
| GET / PATCH / DELETE | `addresses/{id}/` | Read, update or delete one of your own addresses |

### Other

| Endpoint | Description |
|---|---|
| `health/` | Health check used by Docker |
| `admin/` | Django admin |

## Example

```bash
# Register
curl -c cookies.txt -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"Str0ng-Passw0rd!","first_name":"You"}' \
  http://localhost:8001/api/v1/auth/register/

# Use the access token from the response
curl -H "Authorization: Bearer <access>" http://localhost:8001/api/v1/users/me/

# Get a new access token using the refresh cookie
curl -b cookies.txt -c cookies.txt -X POST http://localhost:8001/api/v1/auth/refresh/
```

## Security

- **Passwords** hashed with Argon2; Django's validators reject short, common, numeric-only and name-like passwords.
- **Refresh tokens** live in an `httpOnly`, `SameSite=Lax` cookie, so JavaScript cannot read them and other sites cannot send them in cross-site POSTs.
- **Token rotation:** every refresh issues a new refresh token and blacklists the old one, so a stolen token works at most once. Logout and password changes revoke the current token.
- **Rate limiting** on register, login and refresh (default 10 per minute per client), stored in Redis.
- **No account enumeration:** a wrong email and a wrong password return the same error.
- **Ownership checks:** address queries are always filtered by the logged-in user; another user's address returns 404.
- **Public signup cannot create admins.** Admins are created with `createsuperuser`.
- **UUID primary keys,** so ids can't be guessed or counted.
- **Weak keys refused:** outside debug mode the service won't start with a signing key shorter than 32 characters.
- **Non-root container** user.

## Running

From the repository root:

```bash
docker compose up -d users           # starts Postgres, Redis and this service
docker compose exec users python manage.py createsuperuser
```

The API is on http://localhost:8001.

## Tests

```bash
docker compose run --rm users pytest
```

43 tests cover registration, login, token rotation and revocation, rate limiting, profile updates, password changes and address ownership. They run against PostgreSQL, the same database used in production.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DJANGO_SECRET_KEY` | required | At least 32 characters outside debug mode |
| `JWT_SIGNING_KEY` | `DJANGO_SECRET_KEY` | Separate key for signing JWTs |
| `DJANGO_DEBUG` | `false` | Debug mode |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | `users_db`, required, required, `localhost`, `5432` | PostgreSQL connection |
| `REDIS_URL` | unset (in-memory cache) | Redis for rate-limit counters |
| `AUTH_THROTTLE_RATE` | `10/minute` | Limit for register, login and refresh |
| `JWT_ACCESS_MINUTES` | `15` | Access token lifetime |
| `JWT_REFRESH_DAYS` | `7` | Refresh token lifetime |
| `REFRESH_COOKIE_SECURE` | `true` unless debug | Send the cookie over HTTPS only |
| `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS` | `false`, `0` | Enable once HTTPS is in place |
