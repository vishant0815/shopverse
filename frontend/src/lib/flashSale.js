// Flash sales: the sale price shoppers see, the countdown, the units left, and the admin list and form.
// Pure helpers with no network, so `npm test` can run them directly.

export const SALE_TABS = [
  ["", "All"],
  ["live", "Live"],
  ["scheduled", "Scheduled"],
  ["ended", "Ended"],
];

const STATUS = {
  live: { label: "Live", tab: "live" },
  scheduled: { label: "Scheduled", tab: "scheduled" },
  ended: { label: "Ended", tab: "ended" },
  off: { label: "Switched off", tab: "ended" },
  sold_out: { label: "Sold out", tab: "ended" },
};

// How much cheaper the sale price is than the regular price, rounded like the storefront's other badges.
export function discountPercent(regular, sale) {
  const was = Number(regular);
  const now = Number(sale);
  return was > 0 && now < was ? Math.round((1 - now / was) * 100) : 0;
}

// Units still open at the sale price. A cap of null or undefined means there is no cap.
export function remainingUnits(cap, sold = 0) {
  return Math.max(Number(cap) - Number(sold || 0), 0);
}

// The smaller of the known values, so inventory and a sale cap combine into one number.
export function minDefined(...values) {
  const known = values.filter((value) => value !== undefined && value !== null);
  return known.length ? Math.min(...known) : undefined;
}

export function remainingLabel(left) {
  if (left === undefined || left === null) return null;
  if (left === 0) return "Sold out at this price";
  return `Only ${left} left at this price`;
}

// 02:14:37 for a sale ending today, "2d 03:00:00" for longer.
export function countdown(ms) {
  const total = Math.max(Math.floor(ms / 1000), 0);
  const days = Math.floor(total / 86400);
  const clock = [Math.floor((total % 86400) / 3600), Math.floor((total % 3600) / 60), total % 60]
    .map((part) => String(part).padStart(2, "0"))
    .join(":");
  return days ? `${days}d ${clock}` : clock;
}

// Whether every item in the sale has reached its cap. A sale with any uncapped item is never sold out.
function soldOut(sale, soldByItem) {
  return sale.items.length > 0 && sale.items.every(
    (item) => item.quantity_cap !== null && remainingUnits(item.quantity_cap, soldByItem[item.id]) === 0,
  );
}

// Where a sale stands now. `soldByItem` maps item ids to units sold, from the orders service.
export function saleStatus(sale, now = new Date(), soldByItem = {}) {
  if (!sale.is_active) return "off";
  if (new Date(sale.starts_at) > now) return "scheduled";
  if (new Date(sale.ends_at) <= now) return "ended";
  return soldOut(sale, soldByItem) ? "sold_out" : "live";
}

export function saleStatusLabel(status) {
  return STATUS[status].label;
}

export function statusInTab(status, tab) {
  return tab === "" || STATUS[status].tab === tab;
}

// The sale window in London time, for example "Sat 15 Nov, 09:00 to Sun 16 Nov, 21:00".
export function windowText(sale) {
  const part = (iso) => new Date(iso).toLocaleString("en-GB", {
    weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/London",
  });
  return `${part(sale.starts_at)} to ${part(sale.ends_at)}`;
}

// Units sold across a sale's capped items, for example "84 of 200". "No cap" when nothing is capped.
export function soldText(sale, soldByItem = {}) {
  const capped = sale.items.filter((item) => item.quantity_cap !== null);
  if (!capped.length) return "No cap";
  const sold = capped.reduce((total, item) => total + Number(soldByItem[item.id] || 0), 0);
  const cap = capped.reduce((total, item) => total + item.quantity_cap, 0);
  return `${sold} of ${cap}`;
}

// The admin form as the API takes it. Blank dates become null, which the API rejects with a message.
function isoOrNull(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

export function saleRequest(form) {
  return {
    name: String(form.name ?? "").trim(),
    starts_at: isoOrNull(form.starts_at),
    ends_at: isoOrNull(form.ends_at),
    items: form.items.map((item) => ({
      variant: item.variant,
      sale_price: String(item.sale_price ?? "").trim(),
      quantity_cap: item.quantity_cap === "" || item.quantity_cap === null || item.quantity_cap === undefined
        ? null
        : Number(item.quantity_cap),
    })),
  };
}
