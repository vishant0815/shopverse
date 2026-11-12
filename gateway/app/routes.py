"""Which service handles which path.

Paths are forwarded unchanged (the services already serve /api/v1/...), so a service's
own links, redirects and cookie paths stay correct. The longest matching prefix wins,
which is how /api/v1/seller/products/ goes to products while /api/v1/seller/sales/
goes to orders.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Route:
    prefix: str
    service: str
    # When set, the request is sent to this path instead of its own.
    rewrite_to: str | None = None


ROUTES = [
    Route("/api/v1/auth/", "users"),
    Route("/api/v1/users/", "users"),
    Route("/api/v1/addresses/", "users"),
    Route("/api/v1/categories/", "products"),
    Route("/api/v1/products/", "products"),
    Route("/api/v1/variants/", "products"),
    Route("/api/v1/seller/products/", "products"),
    Route("/api/v1/cart/", "orders"),
    Route("/api/v1/checkout/", "orders"),
    Route("/api/v1/orders/", "orders"),
    Route("/api/v1/seller/sales/", "orders"),
    Route("/api/v1/seller/summary/", "orders"),
    Route("/api/v1/admin/", "orders"),
    Route("/api/v1/payments/", "payments"),
    # Stock levels for the storefront and the seller editor (read-only for shoppers).
    Route("/api/v1/inventory/", "inventory"),
    # Product search and autosuggest (read-only; the index is fed by catalogue events).
    Route("/api/v1/search/", "search"),
    Route("/api/v1/webhooks/", "payments"),
    # The checkout page asks this to find out which payment provider is switched on.
    Route("/api/payments-health", "payments", rewrite_to="/health"),
]

_BY_LENGTH = sorted(ROUTES, key=lambda r: len(r.prefix), reverse=True)


def match(path: str) -> Route | None:
    for route in _BY_LENGTH:
        if route.rewrite_to:
            if path == route.prefix:
                return route
            continue
        # "/api/v1/cart" (no slash) still belongs to the cart; the service redirects it.
        if path.startswith(route.prefix) or path == route.prefix.rstrip("/"):
            return route
    return None
