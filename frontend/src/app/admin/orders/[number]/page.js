"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import PanelShell from "@/components/panel/PanelShell";
import { NEXT_STEPS, confirmMessage } from "@/components/panel/orderActions";
import StatusBadge from "@/components/StatusBadge";
import { Button, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTime, money, orderStatus, variantLabel } from "@/lib/format";

function AdminOrder() {
  const { number } = useParams();
  const [order, setOrder] = useState(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(null);

  const load = useCallback(async () => {
    try {
      setOrder(await api(`/api/v1/admin/orders/${encodeURIComponent(number)}/`));
    } catch (err) {
      setError(err.status === 404 ? "There's no order with that number." : err.message);
    }
  }, [number]);

  useEffect(() => {
    load();
  }, [load]);

  async function move(step) {
    const message = confirmMessage(order, step);
    if (message && !window.confirm(message)) return;
    setBusy(step.status);
    setError("");
    try {
      setOrder(await api(`/api/v1/admin/orders/${encodeURIComponent(number)}/transition/`, {
        method: "POST",
        body: { status: step.status, note: note.trim() },
      }));
      setNote("");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(null);
    }
  }

  if (!order) return error ? <Notice>{error}</Notice> : <p className="py-16 text-ink-soft">Loading order…</p>;

  const steps = NEXT_STEPS[order.status] || [];
  const address = order.shipping_address;

  return (
    <>
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <Link href="/admin/orders" className="text-sm font-medium text-accent hover:underline">All orders</Link>
          <h1 className="mt-1 font-mono text-3xl font-extrabold sm:text-4xl">{order.number}</h1>
          <p className="mt-2 text-ink-soft">Placed {dateTime(order.created_at)} · customer <span className="font-mono text-sm">{order.user_id.slice(0, 8)}</span></p>
        </div>
        <StatusBadge status={order.status} />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1fr_340px]">
        <section aria-labelledby="items-heading" className="raised p-6">
          <h2 id="items-heading" className="mb-5 text-2xl font-bold">Items</h2>
          <ul className="space-y-4">
            {order.items.map((item) => (
              <li key={item.sku} className="flex items-center gap-4">
                <div className="inset h-16 w-16 shrink-0 overflow-hidden rounded-lg">
                  {item.thumbnail && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={item.thumbnail} alt="" className="photo h-full w-full object-cover" />
                  )}
                </div>
                <div className="flex flex-1 flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="font-semibold">{item.product_name}</p>
                    <p className="text-sm text-ink-soft">
                      {[item.sku, variantLabel(item), `${item.quantity} × ${money(item.unit_price)}`].filter(Boolean).join(" · ")}
                    </p>
                  </div>
                  <span className="font-display font-extrabold">{money(item.line_total)}</span>
                </div>
              </li>
            ))}
          </ul>
          <dl className="ml-auto mt-6 max-w-xs space-y-2 border-t border-line pt-5">
            <div className="flex justify-between"><dt>Items</dt><dd>{money(order.subtotal)}</dd></div>
            <div className="flex justify-between"><dt>Delivery</dt><dd>{Number(order.shipping_fee) === 0 ? "Free" : money(order.shipping_fee)}</dd></div>
            <div className="flex justify-between pt-2 font-display text-2xl font-extrabold"><dt>Total</dt><dd className="metal-text">{money(order.total)}</dd></div>
          </dl>
        </section>

        <aside className="space-y-6">
          <section aria-labelledby="actions-heading" className="raised p-6">
            <h2 id="actions-heading" className="mb-4 text-xl font-bold">Next step</h2>
            {steps.length === 0 ? (
              <p className="text-ink-soft">
                {order.status === "pending_payment" ? "" : "Nothing left to do: this order is finished."}
              </p>
            ) : (
              <>
                {order.status === "pending_payment" && (
                  <p className="mb-4 text-sm text-ink-soft">Waiting for the customer to pay. The payment service marks it paid automatically.</p>
                )}
                <label className="block">
                  <span className="mb-1.5 block text-sm font-medium">Note for the history (optional)</span>
                  <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={255}
                    placeholder="e.g. Royal Mail tracking AB123456789GB" className="field px-3 py-2 text-sm" />
                </label>
                <div className="mt-4 flex flex-wrap gap-3">
                  {steps.map((step) => (
                    <Button key={step.status} variant={step.variant} busy={busy === step.status} onClick={() => move(step)}>
                      {busy === step.status ? "Saving…" : step.label}
                    </Button>
                  ))}
                </div>
              </>
            )}
            <div className="mt-4"><Notice>{error}</Notice></div>
          </section>

          <section aria-labelledby="address-heading" className="raised p-6">
            <h2 id="address-heading" className="mb-3 text-xl font-bold">Delivering to</h2>
            <address className="not-italic leading-relaxed text-ink-soft">
              {address.full_name}<br />
              {address.line1}<br />
              {address.line2 && <>{address.line2}<br /></>}
              {address.city} {address.postcode}<br />
              {address.phone}
            </address>
          </section>

          <section aria-labelledby="history-heading" className="raised p-6">
            <h2 id="history-heading" className="mb-4 text-xl font-bold">History</h2>
            <ol className="space-y-4 text-sm">
              {order.history.map((entry, index) => (
                <li key={index} className="flex gap-3">
                  <span aria-hidden="true" className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${
                    entry.to_status === "pending_payment" || entry.to_status === "cancelled" ? "bg-power" : "bg-accent"
                  }`} />
                  <span>
                    <span className="font-semibold">{orderStatus(entry.to_status)}</span>
                    <span className="block text-ink-soft">{dateTime(entry.created_at)}{entry.note ? `: ${entry.note}` : ""}</span>
                  </span>
                </li>
              ))}
            </ol>
          </section>
        </aside>
      </div>
    </>
  );
}

export default function AdminOrderPage() {
  return (
    <PanelShell role="admin">
      <AdminOrder />
    </PanelShell>
  );
}
