// The storefront is also the API gateway for the browser: every request goes to
// this same origin and is forwarded to the right service. That means no CORS setup,
// and the users service's refresh-token cookie (path /api/v1/auth/) just works,
// because paths are forwarded unchanged.
//
// Service addresses are read when the app is built (rewrites are compiled in).
const services = {
  users: process.env.USERS_API_URL || "http://localhost:8001",
  products: process.env.PRODUCTS_API_URL || "http://localhost:8002",
  orders: process.env.ORDERS_API_URL || "http://localhost:8003",
  payments: process.env.PAYMENTS_API_URL || "http://localhost:8004",
};

const routes = [
  ["/api/v1/auth/:path*", "users"],
  ["/api/v1/users/:path*", "users"],
  ["/api/v1/addresses/:path*", "users"],
  ["/api/v1/categories/:path*", "products"],
  ["/api/v1/products/:path*", "products"],
  ["/api/v1/variants/:path*", "products"],
  ["/api/v1/seller/products/:path*", "products"],
  ["/api/v1/cart/:path*", "orders"],
  ["/api/v1/checkout/:path*", "orders"],
  ["/api/v1/orders/:path*", "orders"],
  ["/api/v1/seller/sales/:path*", "orders"],
  ["/api/v1/payments/:path*", "payments"],
  ["/api/payments-health", "payments", "/health"],
];

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // Django URLs end in "/", so Next must not redirect them to the slash-less form.
  skipTrailingSlashRedirect: true,
  poweredByHeader: false,
  async rewrites() {
    return routes.flatMap(([source, service, target]) => {
      const base = services[service];
      if (target) return [{ source, destination: `${base}${target}` }];
      // ":path*" doesn't capture a trailing slash, so without the first rule "/api/v1/cart/"
      // would be forwarded as "/api/v1/cart", Django would redirect back to the slash
      // version, and the browser would loop. Keep the slash when the request has one.
      const prefix = source.replace("/:path*", "");
      return [
        { source: `${prefix}/`, destination: `${base}${prefix}/` },
        { source: `${prefix}/:path+/`, destination: `${base}${prefix}/:path+/` },
        { source: `${prefix}/:path*`, destination: `${base}${prefix}/:path*` },
      ];
    });
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
};

export default nextConfig;
