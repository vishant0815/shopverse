// In Docker the API gateway sits in front of this app: it serves the pages from here and
// sends /api/... straight to the services, so these rewrites are never used there.
// They're for `npm run dev`, where the browser talks to this app directly: API requests
// are passed, path unchanged, to the gateway. Either way the browser sees one origin, so
// there's no CORS setup and the refresh-token cookie (path /api/v1/auth/) just works.
//
// The gateway address is read when the app is built (rewrites are compiled in).
const gateway = process.env.GATEWAY_URL || "http://localhost:3000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // Django URLs end in "/", so Next must not redirect them to the slash-less form.
  skipTrailingSlashRedirect: true,
  poweredByHeader: false,
  async rewrites() {
    // ":path*" doesn't capture a trailing slash, so without the first rule
    // "/api/v1/cart/" would be forwarded as "/api/v1/cart", Django would redirect back
    // to the slash version, and the browser would loop. Keep the slash when it's there.
    return [
      { source: "/api/:path+/", destination: `${gateway}/api/:path+/` },
      { source: "/api/:path*", destination: `${gateway}/api/:path*` },
    ];
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
