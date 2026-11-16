"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import PanelShell, { PageTitle } from "@/components/panel/PanelShell";
import { Notice } from "@/components/ui";
import { api } from "@/lib/api";
import {
  SALE_TABS,
  saleStatus,
  saleStatusLabel,
  soldText,
  statusInTab,
  windowText,
} from "@/lib/flashSale";

// The orders service counts units; it takes at most 100 item ids per request.
const SOLD_LOOKUP_LIMIT = 100;

function pillClass(status) {
  return status === "live"
    ? "text-accent shadow-[inset_0_0_0_2px_var(--accent)]"
    : "text-ink-soft shadow-[inset_0_0_0_2px_var(--line)]";
}

function FlashSales() {
  const [tab, setTab] = useState("");
  const [sales, setSales] = useState(null);
  const [sold, setSold] = useState({});
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(null);

  const load = useCallback(async () => {
    try {
      const data = await api("/api/v1/admin/flash-sales/");
      setSales(data.results);
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Sold counts come from the orders service, so they are fetched separately and kept in step with the list.
  const itemIds = useMemo(
    () => (sales || []).flatMap((sale) => sale.items.map((item) => item.id)).slice(0, SOLD_LOOKUP_LIMIT),
    [sales],
  );
  useEffect(() => {
    if (!itemIds.length) return;
    api(`/api/v1/flash-sales/sold/?items=${itemIds.join(",")}`)
      .then((data) => setSold(data.results))
      .catch(() => setSold({}));
  }, [itemIds]);

  async function setActive(sale, isActive) {
    setBusy(sale.id);
    setError("");
    setNotice("");
    try {
      await api(`/api/v1/admin/flash-sales/${sale.id}/`, { method: "PATCH", body: { is_active: isActive } });
      setNotice(`${sale.name} is switched ${isActive ? "on" : "off"}.`);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(null);
    }
  }

  const now = new Date();
  const statuses = (sales || []).map((sale) => [sale, saleStatus(sale, now, sold)]);
  const rows = statuses.filter(([, status]) => statusInTab(status, tab));

  return (
    <PanelShell role="admin">
      <PageTitle
        title="Flash sales"
        lede="Time-boxed prices on chosen items. Each item sells at its sale price until the sale ends or its cap is reached. Switching a sale off stops it at once."
        actions={<Link href="/admin/flash-sales/new" className="btn btn-metal">New flash sale</Link>}
      />

      <div className="mb-6 flex flex-wrap gap-2.5" role="group" aria-label="Filter flash sales by status">
        {SALE_TABS.map(([value, label]) => {
          const count = statuses.filter(([, status]) => statusInTab(status, value)).length;
          return (
            <button
              key={label}
              type="button"
              aria-pressed={tab === value}
              onClick={() => setTab(value)}
              className={`rounded-xl px-4 py-2 font-semibold ${tab === value ? "pressed text-accent" : "raised text-ink-soft hover:text-accent"}`}
            >
              {label} ({count})
            </button>
          );
        })}
      </div>

      <div className="mb-4 space-y-3">
        <Notice tone="error">{error}</Notice>
        <Notice tone="success">{notice}</Notice>
      </div>

      {sales === null && !error && <p className="text-ink-soft">Loading flash sales…</p>}
      {sales && rows.length === 0 && <p className="raised p-6 text-ink-soft">No flash sales here yet.</p>}

      {sales && rows.length > 0 && (
        <div className="raised overflow-x-auto px-5">
          <table className="w-full min-w-[820px] border-collapse text-left text-[15px]">
            <thead>
              <tr className="text-sm text-ink-soft">
                <th scope="col" className="py-4 pr-4 font-semibold">Name</th>
                <th scope="col" className="py-4 pr-4 font-semibold">Window (London time)</th>
                <th scope="col" className="py-4 pr-4 font-semibold">Items</th>
                <th scope="col" className="py-4 pr-4 font-semibold">Sold</th>
                <th scope="col" className="py-4 pr-4 font-semibold">Status</th>
                <th scope="col" className="py-4 text-right font-semibold"><span className="sr-only">Action</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map(([sale, status]) => {
                const canSwitch = status === "live" || status === "scheduled" || status === "off";
                const switchingOn = status === "off";
                return (
                  <tr key={sale.id} className="border-t border-line">
                    <td className="py-4 pr-4 font-display font-bold">{sale.name}</td>
                    <td className="py-4 pr-4 text-ink-soft">{windowText(sale)}</td>
                    <td className="py-4 pr-4">{sale.items.length}</td>
                    <td className="py-4 pr-4">{soldText(sale, sold)}</td>
                    <td className="py-4 pr-4">
                      <span className={`inline-block rounded-full px-3 py-0.5 text-sm font-semibold ${pillClass(status)}`}>
                        {saleStatusLabel(status)}
                      </span>
                    </td>
                    <td className="py-4 text-right">
                      {canSwitch ? (
                        <button
                          type="button"
                          onClick={() => setActive(sale, switchingOn)}
                          disabled={busy === sale.id}
                          className="btn btn-soft px-4 py-2 text-sm"
                        >
                          {switchingOn ? "Switch on" : "Switch off"}
                        </button>
                      ) : (
                        <span className="text-ink-soft">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </PanelShell>
  );
}

export default function AdminFlashSalesPage() {
  return <FlashSales />;
}
