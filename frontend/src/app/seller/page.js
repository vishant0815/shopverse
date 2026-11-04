"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import PanelShell, { PageTitle } from "@/components/panel/PanelShell";
import SalesTable from "@/components/panel/SalesTable";
import UnitsChart from "@/components/panel/UnitsChart";
import { Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { money } from "@/lib/format";
import { useSession } from "@/lib/session";

function greeting() {
  const hour = new Date().getHours();
  return hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
}

function Kpi({ label, value, note, tone = "ink", metal = false }) {
  const noteTone = tone === "power" ? "text-power" : "text-accent";
  return (
    <div className="raised p-5">
      <p className="text-sm text-ink-soft">{label}</p>
      <p className={`mt-1.5 font-display text-3xl font-extrabold ${metal ? "metal-text" : tone === "power" ? "text-power" : ""}`}>{value}</p>
      {note && <p className={`mt-1 text-sm font-semibold ${noteTone}`}>{note}</p>}
    </div>
  );
}

function Dashboard() {
  const { user } = useSession();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const [summary, sales, live, drafts] = await Promise.all([
          api("/api/v1/seller/summary/"),
          api("/api/v1/seller/sales/"),
          api("/api/v1/seller/products/?status=active&page_size=1"),
          api("/api/v1/seller/products/?status=draft&page_size=1"),
        ]);
        setData({ summary, sales: sales.results.slice(0, 5), live: live.count, drafts: drafts.count });
      } catch (err) {
        setError(err.message);
      }
    })();
  }, []);

  if (!data) return error ? <Notice>{error}</Notice> : <p className="py-16 text-ink-soft">Loading your shop…</p>;
  const { summary, sales } = data;

  return (
    <>
      <PageTitle title={`${greeting()}, ${user.first_name}`} lede="Here's how your shop is doing." />

      <div className="mb-8 grid grid-cols-2 gap-5 xl:grid-cols-4">
        <Kpi label="Sales" value={money(summary.revenue)} metal note={`from ${summary.orders} ${summary.orders === 1 ? "order" : "orders"}`} />
        <Kpi label="Units sold" value={summary.units_sold} note={`across ${summary.products_sold} ${summary.products_sold === 1 ? "product" : "products"}`} />
        <Kpi
          label="To ship"
          value={summary.to_ship}
          tone={summary.to_ship > 0 ? "power" : "ink"}
          note={summary.to_ship > 0 ? "paid, not shipped yet" : "all caught up"}
        />
        <Kpi label="Live products" value={data.live} note={data.drafts ? `${data.drafts} ${data.drafts === 1 ? "draft" : "drafts"}` : "no drafts"} />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
        <section className="raised min-w-0 p-6" aria-labelledby="recent-heading">
          <div className="mb-4 flex items-baseline justify-between">
            <h2 id="recent-heading" className="text-2xl font-bold">Recent sales</h2>
            <Link href="/seller/sales" className="text-sm font-semibold text-accent hover:underline">See all</Link>
          </div>
          {sales.length === 0 ? (
            <p className="text-ink-soft">No sales yet. They&apos;ll appear here as soon as someone orders one of your products.</p>
          ) : (
            <SalesTable sales={sales} compact />
          )}
        </section>
        <section className="raised p-6" aria-labelledby="chart-heading">
          <h2 id="chart-heading" className="mb-4 text-2xl font-bold">Units sold, last 7 days</h2>
          <UnitsChart days={summary.daily_units} />
        </section>
      </div>
    </>
  );
}

export default function SellerDashboardPage() {
  return (
    <PanelShell role="seller">
      <Dashboard />
    </PanelShell>
  );
}
