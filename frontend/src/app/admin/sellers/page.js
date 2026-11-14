"use client";

import { useCallback, useEffect, useState } from "react";

import PanelShell, { PageTitle } from "@/components/panel/PanelShell";
import { Button, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { ADMIN_TABS, adminActions, confirmSuspend, sellersQuery, shopStatusLabel } from "@/lib/seller";

const PILL = {
  pending: "text-ink-soft shadow-[inset_0_0_0_2px_var(--line)]",
  approved: "text-accent shadow-[inset_0_0_0_2px_var(--accent)]",
  suspended: "text-power shadow-[inset_0_0_0_2px_var(--power)]",
};

function joined(iso) {
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

function Sellers() {
  const [status, setStatus] = useState("");
  const [sellers, setSellers] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(null);

  const load = useCallback(async () => {
    try {
      const data = await api(sellersQuery(status));
      setSellers(data.results);
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }, [status]);

  useEffect(() => {
    load();
  }, [load]);

  async function act(seller, action) {
    if (action === "suspend" && !window.confirm(confirmSuspend(seller.shop_name))) return;
    setBusy(`${seller.seller_id}:${action}`);
    setError("");
    setNotice("");
    try {
      const updated = await api(`/api/v1/admin/sellers/${seller.seller_id}/${action}/`, { method: "POST" });
      setNotice(`${updated.shop_name} is now ${shopStatusLabel(updated.status).toLowerCase()}.`);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <PanelShell role="admin">
      <PageTitle
        title="Sellers"
        lede="Approve a new shop before it can list products. Suspend a shop to hide its products from shoppers, then reinstate it when the problem is fixed."
      />

      <div className="mb-6 flex flex-wrap gap-2.5" role="group" aria-label="Filter sellers by status">
        {ADMIN_TABS.map(([value, label]) => (
          <button
            key={label}
            type="button"
            aria-pressed={status === value}
            onClick={() => setStatus(value)}
            className={`rounded-xl px-4 py-2 font-semibold ${status === value ? "pressed text-accent" : "raised text-ink-soft hover:text-accent"}`}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="mb-4 space-y-3">
        <Notice tone="error">{error}</Notice>
        <Notice tone="success">{notice}</Notice>
      </div>

      {sellers === null && !error && <p className="text-ink-soft">Loading shops…</p>}
      {sellers && sellers.length === 0 && <p className="raised p-6 text-ink-soft">No shops here yet.</p>}

      {sellers && sellers.length > 0 && (
        <ul className="raised divide-y divide-line px-5">
          {sellers.map((seller) => (
            <li key={seller.seller_id} className="flex flex-wrap items-center justify-between gap-4 py-4">
              <div className="min-w-0">
                <p className="font-display text-lg font-bold">{seller.shop_name}</p>
                <p className="truncate text-sm text-ink-soft">
                  {seller.full_name} · {seller.email} · joined {joined(seller.created_at)}
                </p>
              </div>
              <div className="flex items-center gap-3">
                <span className={`inline-block rounded-full px-3 py-0.5 text-sm font-semibold ${PILL[seller.status] || ""}`}>
                  {shopStatusLabel(seller.status)}
                </span>
                {adminActions(seller.status).map(({ action, label }) => (
                  <Button
                    key={action}
                    variant={action === "suspend" ? "secondary" : "primary"}
                    className="px-4 py-2 text-sm"
                    busy={busy === `${seller.seller_id}:${action}`}
                    onClick={() => act(seller, action)}
                  >
                    {label}
                  </Button>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}
    </PanelShell>
  );
}

export default function AdminSellersPage() {
  return <Sellers />;
}
