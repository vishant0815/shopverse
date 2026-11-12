const gbp = new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP" });

export function money(value) {
  if (value === null || value === undefined || value === "") return "";
  return gbp.format(Number(value));
}

export function date(value) {
  return new Date(value).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function dateTime(value) {
  return new Date(value).toLocaleString("en-GB", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

const STATUS_LABELS = {
  reserving: "Checking stock",
  pending_payment: "Awaiting payment",
  paid: "Paid",
  shipped: "Shipped",
  delivered: "Delivered",
  cancelled: "Cancelled",
};

export function orderStatus(status) {
  return STATUS_LABELS[status] || status;
}

// 754 → "12:34". Used for the time left to pay before items go back on sale.
export function countdown(totalSeconds) {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

export function variantLabel(variant) {
  return [variant.colour, variant.size].filter(Boolean).join(", ");
}
