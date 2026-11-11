# Storefront

The Shopverse website: the shop customers use (browse, filter, search, basket, checkout, payment), plus the seller and admin panels.

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

### Seller and admin panel

Only open to the matching role. Anyone else who signs in sees a short "this area is for sellers/admins" page, and the services check the role in the token again on every request.

| Page | What it does |
|---|---|
| `/seller` | Dashboard: sales total, units sold, orders waiting to ship, live products, recent sales and a 7-day chart |
| `/seller/products` | Your products with status filter and search; archive a product |
| `/seller/products/new`, `/seller/products/{id}` | Product editor: details, category, options (item code, colour, size, price, "was" price), photos, draft/published/archived |
| `/seller/sales` | Every order line for your products, filtered by status. Buyer details stay private |
| `/admin/orders`, `/admin/orders/{number}` | Orders by status with counts; mark shipped or delivered with a note the customer sees; cancel (with a warning that refunds are done by hand) |
| `/admin/categories` | Add, rename, hide and show categories |
| `/admin/products`, `/admin/products/{id}` | Every seller's products, with the same editor |

The product editor saves an existing product in a safe order: options and photos first, then the product itself, so a product is only published once it really has something to buy.

Catalogue pages are rendered on the server, so they arrive as finished HTML (fast first load, readable by search engines). The filter form is a plain HTML form, so filtering works even before JavaScript loads. Pages that depend on the signed-in user run in the browser.

## How it talks to the backend

The browser only ever talks to one origin: the [API gateway](../gateway/README.md). It passes pages, scripts and images to this app, and sends every `/api/...` request straight to the right service after checking the access token and the rate limits. This app isn't published on its own port in Docker.

Server-rendered catalogue pages are the one exception: they read the products service directly over the internal network, since they're cached, read-only and come from this server rather than a visitor.

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

Start everything with Docker Compose (the site is then on `http://localhost:3000`), then run the storefront with live reload on another port:

```bash
cd frontend
npm install
npm run dev -- -p 3001   # http://localhost:3001
```

Its API requests go to the gateway on `localhost:3000`, and catalogue pages read the products service on `localhost:8002`; see `.env.local.example` to change them.

## Tested

The full journey was run in a real Chromium browser against all four services, in both the dark and the light theme: browsing, filtering, sorting, searching, variant picking, registering (including a weak password error shown next to the field), adding to the basket, changing quantities, checking out with a new address, a declined card, a successful payment, staying signed in after reload, the saved address being pre-selected next time, signing out, open-redirect protection, the 404 page and the mobile layout.

The panels were tested the same way, with three browsers at once: the demo seller creates and publishes a product, changes its price and adds an option; a new customer finds it in the shop, buys it and pays; the seller sees the sale on the dashboard; the admin marks it shipped with a tracking note and then delivered; the customer sees both changes and the note; the admin adds a category (a duplicate name is refused), hides and shows it, and finds the product; the seller archives it and it leaves the shop; and a customer trying to open `/seller` or `/admin` is turned away. Both walkthroughs now run through the API gateway, in both themes. Automating them in CI is on the roadmap.
