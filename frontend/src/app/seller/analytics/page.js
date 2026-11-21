"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import PanelShell, { PageTitle } from "@/components/panel/PanelShell";
import { Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { barHeights, conversionLabel, dayLabel } from "@/lib/analytics";

const RANGES = [
  [7, "7 days"],
  [30, "30 days"],
];

function Stat({ label, value, hint }) {
  return (
    <div className="raised flex flex-col gap-1 p-5">
      <span className="text-sm text-ink-soft">{label}</span>
      <strong className="text-3xl font-extrabold">{value}</strong>
      {hint && <span className="text-xs text-ink-soft">{hint}</span>}
    </div>
  );
}

// One bar per day, sized against the busiest day. Each bar names its day and count when hovered,
// and the table under the chart gives the same numbers for anyone who can't use the bars.
function DailyUnits({ daily }) {
  const heights = barHeights(daily.map((day) => day.units_sold));
  const first = daily[0];
  const last = daily[daily.length - 1];

  return (
    <section aria-labelledby="units-by-day" className="raised p-5">
      <h2 id="units-by-day" className="text-lg font-bold">Units sold by day</h2>
      <div className="mt-5 flex h-44 items-end gap-1">
        {daily.map((day, index) => (
          <div
            key={day.date}
            title={`${dayLabel(day.date)}: ${day.units_sold} sold`}
            aria-hidden="true"
            className="flex h-full min-w-0 flex-1 items-end"
          >
            <div
              className="w-full rounded-t bg-accent"
              style={{ height: `${heights[index]}%`, minHeight: day.units_sold > 0 ? "3px" : "0" }}
            />
          </div>
        ))}
      </div>
      <div className="mt-2 flex justify-between text-xs text-ink-soft" aria-hidden="true">
        <span>{dayLabel(first.date)}</span>
        <span>{dayLabel(last.date)}</span>
      </div>
      <details className="mt-4">
        <summary className="cursor-pointer font-semibold text-accent">Show the daily figures as a table</summary>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Views, add to baskets and units sold for each day</caption>
            <thead>
              <tr className="border-b border-line">
                <th scope="col" className="py-2 pr-4 font-semibold">Day</th>
                <th scope="col" className="py-2 pr-4 font-semibold">Views</th>
                <th scope="col" className="py-2 pr-4 font-semibold">Added to basket</th>
                <th scope="col" className="py-2 font-semibold">Units sold</th>
              </tr>
            </thead>
            <tbody>
              {daily.map((day) => (
                <tr key={day.date} className="border-b border-line/60">
                  <td className="py-2 pr-4">{dayLabel(day.date)}</td>
                  <td className="py-2 pr-4">{day.views}</td>
                  <td className="py-2 pr-4">{day.add_to_carts}</td>
                  <td className="py-2">{day.units_sold}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}

function ProductTable({ products }) {
  return (
    <section aria-labelledby="by-product" className="raised p-5">
      <h2 id="by-product" className="text-lg font-bold">By product</h2>
      {products.length === 0 ? (
        <p className="mt-4 text-ink-soft">No product activity in these days.</p>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Your products, most units sold first</caption>
            <thead>
              <tr className="border-b border-line">
                <th scope="col" className="py-2 pr-4 font-semibold">Product</th>
                <th scope="col" className="py-2 pr-4 font-semibold">Views</th>
                <th scope="col" className="py-2 pr-4 font-semibold">Added to basket</th>
                <th scope="col" className="py-2 font-semibold">Units sold</th>
              </tr>
            </thead>
            <tbody>
              {products.map((product) => (
                <tr key={product.product_id} className="border-b border-line/60">
                  <td className="py-2 pr-4">
                    <Link href={`/products/${product.slug}`} className="font-semibold hover:text-accent">
                      {product.name}
                    </Link>
                  </td>
                  <td className="py-2 pr-4">{product.views}</td>
                  <td className="py-2 pr-4">{product.add_to_carts}</td>
                  <td className="py-2">{product.units_sold}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Report({ data }) {
  const { totals, daily, products } = data;
  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Product views" value={totals.views} />
        <Stat label="Added to basket" value={totals.add_to_carts} />
        <Stat label="Units sold" value={totals.units_sold} />
        <Stat
          label="Basket rate"
          value={conversionLabel(totals.add_to_cart_rate)}
          hint="Share of product views that led to an add to basket"
        />
      </div>
      <DailyUnits daily={daily} />
      <ProductTable products={products} />
      {products.length >= 50 && (
        <p className="text-sm text-ink-soft">Showing the top 50 products by units sold. The totals above cover all of them.</p>
      )}
    </div>
  );
}

function Analytics() {
  const [days, setDays] = useState(7);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let current = true;
    setData(null);
    setError("");
    api(`/api/v1/seller/analytics/?days=${days}`)
      .then((body) => { if (current) setData(body); })
      .catch((err) => { if (current) setError(err.message); });
    return () => { current = false; };
  }, [days]);

  return (
    <>
      <PageTitle
        title="Analytics"
        lede="How shoppers find your products and what they buy. Days are counted in UTC."
      />
      <div className="mb-6 flex flex-wrap gap-3" role="group" aria-label="Date range">
        {RANGES.map(([value, label]) => (
          <button
            key={value}
            type="button"
            aria-pressed={days === value}
            onClick={() => setDays(value)}
            className={`raised-sm px-4 py-2 font-semibold ${days === value ? "pressed" : "hover:text-accent"}`}
          >
            {label}
          </button>
        ))}
      </div>
      <Notice>{error}</Notice>
      {!data && !error && <p className="text-ink-soft">Loading analytics…</p>}
      {data && <Report data={data} />}
    </>
  );
}

export default function SellerAnalyticsPage() {
  return (
    <PanelShell role="seller">
      <Analytics />
    </PanelShell>
  );
}
