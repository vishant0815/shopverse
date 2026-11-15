// Coupon codes: how a code reads on the basket and in the admin list, and how the admin form
// becomes a request. Pure helpers with no network, so `npm test` can run them directly.

export const COUPON_TABS = [
  ["", "All"],
  ["active", "Active"],
  ["scheduled", "Scheduled"],
  ["ended", "Ended"],
];

// Each status, its label and the tab it belongs to. "Switched off" codes sit under Ended:
// they can't be used until someone switches them back on.
const STATUS = {
  active: { label: "Active", tab: "active" },
  scheduled: { label: "Scheduled", tab: "scheduled" },
  expired: { label: "Expired", tab: "ended" },
  used_up: { label: "Used up", tab: "ended" },
  off: { label: "Switched off", tab: "ended" },
};

const DAY = { day: "numeric", month: "short", year: "numeric" };

export function normalizeCode(code) {
  return String(code ?? "").trim().toUpperCase();
}

// "10% off", or "£5.00 off" for a fixed amount. `coupon` is the coupon as the API returns it.
export function discountLabel(coupon) {
  if (coupon.kind === "percent") return `${Number(coupon.value)}% off`;
  return `£${Number(coupon.value).toFixed(2)} off`;
}

// Where a code stands now, from its switch, its dates and its uses. `now` is a parameter so
// the tests can fix the time.
export function couponStatus(coupon, now = new Date()) {
  if (!coupon.is_active) return "off";
  if (coupon.starts_at && new Date(coupon.starts_at) > now) return "scheduled";
  if (coupon.ends_at && new Date(coupon.ends_at) <= now) return "expired";
  if (coupon.usage_limit !== null && coupon.used_count >= coupon.usage_limit) return "used_up";
  return "active";
}

export function couponStatusLabel(status) {
  return STATUS[status].label;
}

export function statusInTab(status, tab) {
  return tab === "" || STATUS[status].tab === tab;
}

// "Starts 25 Nov 2026", "Ends 31 Dec 2026", "Ended 31 Aug 2026", or "No end date".
export function validityText(coupon, now = new Date()) {
  const day = (iso) => new Date(iso).toLocaleDateString("en-GB", DAY);
  if (coupon.starts_at && new Date(coupon.starts_at) > now) return `Starts ${day(coupon.starts_at)}`;
  if (coupon.ends_at) {
    return new Date(coupon.ends_at) <= now ? `Ended ${day(coupon.ends_at)}` : `Ends ${day(coupon.ends_at)}`;
  }
  return "No end date";
}

// How many times a code has been used, for example "84 of 200 · 1 per customer".
export function usageText(coupon) {
  const parts = [`${coupon.used_count}${coupon.usage_limit !== null ? ` of ${coupon.usage_limit}` : ""}`];
  if (coupon.per_customer_limit !== null) parts.push(`${coupon.per_customer_limit} per customer`);
  return parts.join(" · ");
}

// The admin form as the API takes it: codes in capitals, money as text, and empty optional
// fields left out.
export function couponRequest(form) {
  const optionalDate = (value) => (value ? new Date(value).toISOString() : null);
  const optionalNumber = (value) => (value === "" || value === null || value === undefined ? null : Number(value));
  return {
    code: normalizeCode(form.code),
    kind: form.kind,
    value: String(form.value ?? "").trim(),
    min_subtotal: String(form.min_subtotal ?? "").trim() || "0.00",
    starts_at: optionalDate(form.starts_at),
    ends_at: optionalDate(form.ends_at),
    usage_limit: optionalNumber(form.usage_limit),
    per_customer_limit: optionalNumber(form.per_customer_limit),
  };
}
