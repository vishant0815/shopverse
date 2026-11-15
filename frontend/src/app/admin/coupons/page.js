"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import PanelShell, { PageTitle } from "@/components/panel/PanelShell";
import { Notice } from "@/components/ui";
import { api } from "@/lib/api";
import {
  COUPON_TABS,
  couponStatus,
  couponStatusLabel,
  discountLabel,
  statusInTab,
  usageText,
  validityText,
} from "@/lib/coupon";
import { money } from "@/lib/format";

function pillClass(status) {
  return status === "active"
    ? "text-accent shadow-[inset_0_0_0_2px_var(--accent)]"
    : "text-ink-soft shadow-[inset_0_0_0_2px_var(--line)]";
}

function Coupons() {
  const [tab, setTab] = useState("");
  const [coupons, setCoupons] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(null);

  const load = useCallback(async () => {
    try {
      const data = await api("/api/v1/admin/coupons/");
      setCoupons(data.results);
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function setActive(coupon, isActive) {
    setBusy(coupon.code);
    setError("");
    setNotice("");
    try {
      await api(`/api/v1/admin/coupons/${coupon.code}/`, { method: "PATCH", body: { is_active: isActive } });
      setNotice(`${coupon.code} is switched ${isActive ? "on" : "off"}.`);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(null);
    }
  }

  const now = new Date();
  const rows = (coupons || []).filter((coupon) => statusInTab(couponStatus(coupon, now), tab));

  return (
    <PanelShell role="admin">
      <PageTitle
        title="Coupons"
        lede="Codes that take money off a basket. Switch a code off to stop it working straight away. Orders already placed keep their discount."
        actions={<Link href="/admin/coupons/new" className="btn btn-metal">New coupon</Link>}
      />

      <div className="mb-6 flex flex-wrap gap-2.5" role="group" aria-label="Filter coupons by status">
        {COUPON_TABS.map(([value, label]) => {
          const count = (coupons || []).filter((coupon) => statusInTab(couponStatus(coupon, now), value)).length;
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

      {coupons === null && !error && <p className="text-ink-soft">Loading coupons…</p>}
      {coupons && rows.length === 0 && <p className="raised p-6 text-ink-soft">No coupons here yet.</p>}

      {coupons && rows.length > 0 && (
        <div className="raised overflow-x-auto px-5">
          <table className="w-full min-w-[760px] border-collapse text-left text-[15px]">
            <thead>
              <tr className="text-sm text-ink-soft">
                <th scope="col" className="py-4 pr-4 font-semibold">Code</th>
                <th scope="col" className="py-4 pr-4 font-semibold">Discount</th>
                <th scope="col" className="py-4 pr-4 font-semibold">Minimum basket</th>
                <th scope="col" className="py-4 pr-4 font-semibold">Used</th>
                <th scope="col" className="py-4 pr-4 font-semibold">Valid</th>
                <th scope="col" className="py-4 pr-4 font-semibold">Status</th>
                <th scope="col" className="py-4 text-right font-semibold"><span className="sr-only">Action</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((coupon) => {
                const status = couponStatus(coupon, now);
                const canSwitch = status === "active" || status === "scheduled" || status === "off";
                const switchingOn = status === "off";
                return (
                  <tr key={coupon.id} className="border-t border-line">
                    <td className="py-4 pr-4 font-display font-bold tracking-wide">{coupon.code}</td>
                    <td className="py-4 pr-4">{discountLabel(coupon)}</td>
                    <td className="py-4 pr-4">{money(coupon.min_subtotal)}</td>
                    <td className="py-4 pr-4">{usageText(coupon)}</td>
                    <td className="py-4 pr-4 text-ink-soft">{validityText(coupon, now)}</td>
                    <td className="py-4 pr-4">
                      <span className={`inline-block rounded-full px-3 py-0.5 text-sm font-semibold ${pillClass(status)}`}>
                        {couponStatusLabel(status)}
                      </span>
                    </td>
                    <td className="py-4 text-right">
                      {canSwitch ? (
                        <button
                          type="button"
                          onClick={() => setActive(coupon, switchingOn)}
                          disabled={busy === coupon.code}
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

export default function AdminCouponsPage() {
  return <Coupons />;
}
