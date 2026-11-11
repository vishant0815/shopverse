"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import PanelShell, { PageTitle } from "@/components/panel/PanelShell";
import { NEXT_STEPS, confirmMessage } from "@/components/panel/orderActions";
import StatusBadge from "@/components/StatusBadge";
import { Button, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { date, money } from "@/lib/format";

const TABS = [
  ["", "All"],
  ["paid", "To ship"],
  ["shipped", "Shipped"],
  ["delivered", "Delivered"],
  ["pending_payment", "Awaiting payment"],
  ["cancelled", "Cancelled"],
];

function Orders() {
  const [status, setStatus] = useState("paid");
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [counts, setCounts] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(null);

  const load = useCallback(async () => {
    const query = new URLSearchParams({ page: String(page), ...(status ? { status } : {}) });
    try {
      const [list, summary] = await Promise.all([
        api(`/api/v1/admin/orders/?${query}`),
        api("/api/v1/admin/orders/summary/"),
      ]);
      setData(list);
      setCounts(summary);
    } catch (err) {
      setError(err.message);
    }
  }, [status, page]);

  useEffect(() => {
    load();
  }, [load]);

  async function move(order, step) {
    const message = confirmMessage(order, step);
    if (message && !window.confirm(message)) return;
    setBusy(order.number);
    setError("");
    try {
      await api(`/api/v1/admin/orders/${encodeURIComponent(order.number)}/transition/`, {
        method: "POST",
        body: { status: step.status, note: "" },
      });
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(null);
    }
  }

  const countFor = (value) => (counts ? (value ? counts.by_status[value] : counts.total) : null);

  return (
    <>
      <PageTitle title="Orders" lede="Ship paid orders and keep customers up to date. They see every change on their order page." />
      <div className="mb-6 flex flex-wrap gap-3" role="group" aria-label="Filter by status">
        {TABS.map(([value, label]) => {
          const count = countFor(value);
          return (
            <button
              key={value || "all"}
              aria-pressed={status === value}
              onClick={() => { setStatus(value); setPage(1); }}
              className={`raised-sm flex items-center gap-2 px-4 py-2 font-semibold ${status === value ? "pressed" : "hover:text-accent"}`}
            >
              {label}
              {count !== null && (
                <span className={`rounded-full px-2 text-xs leading-5 ${
                  value === "paid" && count > 0 ? "bg-power text-white" : "shadow-[inset_0_0_0_1.5px_var(--line)] text-ink-soft"
                }`}>
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      <Notice>{error}</Notice>

      <section className="raised mt-4 p-4 sm:p-5">
        {!data ? (
          <p className="p-2 text-ink-soft">Loading orders…</p>
        ) : data.results.length === 0 ? (
          <p className="p-2 text-ink-soft">No orders here.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead className="text-sm text-ink-soft">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium">Order</th>
                  <th scope="col" className="px-3 py-2 font-medium">Placed</th>
                  <th scope="col" className="px-3 py-2 font-medium">Items</th>
                  <th scope="col" className="px-3 py-2 font-medium">Status</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Total</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium"><span className="sr-only">Next step</span></th>
                </tr>
              </thead>
              <tbody>
                {data.results.map((order) => (
                  <tr key={order.number} className="border-t border-line">
                    <td className="px-3 py-3">
                      <Link href={`/admin/orders/${encodeURIComponent(order.number)}`} className="font-mono font-semibold hover:text-accent">
                        {order.number}
                      </Link>
                    </td>
                    <td className="whitespace-nowrap px-3 py-3 text-ink-soft">{date(order.created_at)}</td>
                    <td className="px-3 py-3">{order.item_count}</td>
                    <td className="px-3 py-3"><StatusBadge status={order.status} /></td>
                    <td className="whitespace-nowrap px-3 py-3 text-right font-display font-extrabold">
                      <span className="metal-text">{money(order.total)}</span>
                    </td>
                    <td className="whitespace-nowrap px-3 py-3 text-right">
                      {(NEXT_STEPS[order.status] || [])
                        .filter((step) => step.status !== "cancelled")
                        .map((step) => (
                          <Button key={step.status} variant="secondary" className="px-3 py-1.5 text-sm"
                            busy={busy === order.number} onClick={() => move(order, step)}>
                            {step.label}
                          </Button>
                        ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {data && (data.next || data.previous) && (
        <div className="mt-6 flex items-center gap-4">
          <Button variant="secondary" disabled={!data.previous} onClick={() => setPage((p) => p - 1)}>Previous</Button>
          <span className="text-ink-soft">Page {page}</span>
          <Button variant="secondary" disabled={!data.next} onClick={() => setPage((p) => p + 1)}>Next</Button>
        </div>
      )}
    </>
  );
}

export default function AdminOrdersPage() {
  return (
    <PanelShell role="admin">
      <Orders />
    </PanelShell>
  );
}
