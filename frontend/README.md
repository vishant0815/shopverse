# Storefront

The customer-facing website for Shopverse: browse the catalogue, filter and search, pick a variant, fill a basket, check out and pay.

**Stack:** Next.js 15 (App Router), React 19, JavaScript, Tailwind CSS 4, Stripe.js

Runs at http://localhost:3000 after `docker compose up -d --build`.

## Pages

| Page | What it does | Rendered |
|---|---|---|
| `/` | Featured products, newest products, category links | Server |
| `/products` | Catalogue with category tree, price, brand, colour and size filters, search, sorting and pagination | Server |
| `/products/{slug}` | Product page with colour and size picker, sale price and discount | Server, with an interactive picker |
| `/login`, `/register` | Sign in or create an account (customer or seller) | Browser |
| `/cart` | Basket with quantity changes and live totals | Browser |
| `/checkout` | Saved or new delivery address, order summary, place order | Browser |
| `/orders`, `/orders/{number}` | Order history, progress, status history, payment, cancelling | Browser |
| `/account` | Profile details and saved addresses | Browser |

Catalogue pages are rendered on the server, so they arrive as finished HTML (fast first load, readable by search engines). The filter form is a plain HTML form, so filtering works even before JavaScript loads. Pages that depend on the signed-in user run in the browser.

## How it talks to the backend

The browser only ever talks to this site. `next.config.mjs` forwards API paths to the right service, acting as a small API gateway:

| Path | Service |
|---|---|
| `/api/v1/auth/`, `/api/v1/users/`, `/api/v1/addresses/` | users |
| `/api/v1/products/`, `/api/v1/categories/`, `/api/v1/variants/`, `/api/v1/seller/products/` | products |
| `/api/v1/cart/`, `/api/v1/checkout/`, `/api/v1/orders/`, `/api/v1/seller/sales/` | orders |
| `/api/v1/payments/` | payments |

Because everything is on one origin, there's no CORS configuration, and the users service's refresh cookie is sent automatically.

## Sign-in and security

- **Access token in memory only,** never in `localStorage`, so a malicious script can't read it from storage. It's lost on reload by design.
- **Refresh token in an httpOnly cookie,** set by the users service. JavaScript can't read it; on page load the site uses it to get a new access token, so you stay signed in.
- **One refresh at a time.** The refresh token rotates on every use, so parallel refreshes would log the user out. The API client shares one refresh between all waiting requests, and retries a request once after a 401.
- **Safe redirects after sign-in:** `?next=` only accepts paths on this site, so a crafted link can't send someone elsewhere after they log in.
- **Security headers:** `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, a strict referrer policy, and no `X-Powered-By`.
- **Prices are never sent by the browser.** The basket stores only items and quantities; checkout sends the total the customer saw so the server can refuse if a price changed.
- **Double-click safe checkout:** each visit to the checkout page creates an idempotency key, so repeating the request returns the same order.

## Payments

The order page shows a payment panel while an order is awaiting payment. It asks the payments service which provider is active:

- **Fake provider (default):** two buttons, *Pay with a test card* and *Try a declined card*, which go through the same code as a real Stripe webhook.
- **Stripe test mode:** Stripe's card form (Payment Element). Card details go straight to Stripe. Once Stripe confirms, the page waits for the webhook to mark the order paid. Set `STRIPE_PUBLISHABLE_KEY` (`pk_test_...`) in the root `.env` and rebuild.

## Design

**Neumorphism in black and metallic green, with a dark and a light theme.**

- **Surfaces:** every card, button and field is the same colour as the page; depth comes only from a dark and a light shadow. Cards and buttons look raised, fields and selected options look pressed in.
- **Metallic green** (a gradient) for buttons, links, the logo and prices.
- **Red** marks what needs attention or is a deal: discounts, crossed-out old prices, the basket count, "awaiting payment", errors and remove or cancel actions. It's bright red in the dark theme and dark red in the light theme.
- **Prices** sit in a frosted-glass chip on product photos, and in a pressed-in panel on the product page, basket and orders.
- **Type:** Bricolage Grotesque for headings and Instrument Sans for body text, both self-hosted.

### Themes

- The first visit follows the device's light or dark setting; the switch in the header changes it, and the choice is remembered in the browser.
- A tiny script in the page `<head>` sets the theme before anything is drawn, so there's never a flash of the wrong colours.
- All colours are CSS variables (`globals.css`), exposed to Tailwind as `bg-bg`, `text-ink`, `text-accent`, `text-power` and so on, so components never hard-code a colour.

### Motion

- **Theme switch:** going dark, darkness pours out of the switch in a growing circle; going light, it's pulled back in. Built with the View Transitions API (`ThemeSwitch.js`); browsers without it switch instantly.
- Cards lift on hover, buttons press in when clicked, the headline rises in on load, and the basket count pulses when it changes.
- Everything is switched off for people who've asked their device to reduce motion.

### Accessibility

Visible keyboard focus everywhere, a skip link, labelled controls (including the quantity steppers and the theme switch), selected options marked with an outline and not only colour, and no horizontal scrolling on phones.

## Running without Docker

Start the backend services with Docker Compose, then:

```bash
cd frontend
npm install
npm run dev            # http://localhost:3000
```

Service addresses default to `localhost:8001`–`8004`; see `.env.local.example` to change them.

## Tested

The full journey was run in a real Chromium browser against all four services, in both the dark and the light theme: browsing, filtering, sorting, searching, variant picking, registering (including a weak password error shown next to the field), adding to the basket, changing quantities, checking out with a new address, a declined card, a successful payment, staying signed in after reload, the saved address being pre-selected next time, signing out, open-redirect protection, the 404 page and the mobile layout. Automating this walkthrough in CI is on the roadmap.
