// Formatting and chart maths for the seller analytics page. No React here, so it can be tested alone.

// The share of views that led to an add to basket, as a whole percentage.
export function conversionLabel(rate) {
  if (rate === null || rate === undefined) return "No views yet";
  return `${Math.round(rate * 100)}%`;
}

// Bar heights from 0 to 100, scaled to the largest value so the tallest bar fills the chart.
export function barHeights(values) {
  const largest = Math.max(0, ...values);
  return values.map((value) => (largest === 0 ? 0 : Math.round((value / largest) * 100)));
}

// "Wed 18 Nov" for a UTC day such as "2026-11-18". The day is read as UTC so no time zone can move it.
export function dayLabel(isoDate) {
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}
