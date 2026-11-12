"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import PaymentPanel from "@/components/PaymentPanel";
import { LinePrice } from "@/components/Price";
import RequireSignIn from "@/components/RequireSignIn";
import StatusBadge from "@/components/StatusBadge";
import { Button, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { countdown, dateTime, money, orderStatus, variantLabel } from "@/lib/format";

const JOURNEY = ["pending_payment", "paid", "shipped", "delivered"];

// Ticks once a second while `active`, so the hold countdown stays current.
function useNow(active) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  return now;
}

function refundText(refund) {
  const amount = refund.amount ? money(refund.amount) : "your payment";
  if (refund.status === "refunded") return `We've refunded ${amount} to your card.`;
  if (refund.status === "failed") return "The refund needs a closer look, and our team has been told. You don't need to do anything.";
  return `We're refunding ${amount} to your card. This can take a few minutes.`;
}

function OrderDetail() {
  const { number } = useParams();
  const [order, setOrder] = useState(null);
  const [error, setError] = useState("");
  const [cancelling, setCancelling] = useState(false);
  const now = useNow(Boolean(order?.hold_expires_at));

  const load = useCallback(async () => {
    try {
      setOrder(await api(`/api/v1/orders/${encodeURIComponent(number)}/`));
    } catch (err) {
      setError(err.status === 404 ? "We couldn't find that order." : err.message);
    }
  }, [number]);

  useEffect(() => {
    load();
  }, [load]);

  // Stock is still being checked: poll quickly. Items held for payment: poll slowly, so a
  // hold that runs out shows up as cancelled without a reload.
  const settling = order?.status === "reserving";
  const holding = Boolean(order?.hold_expires_at);
  useEffect(() => {
    if (!settling && !holding) return undefined;
    const timer = setInterval(load, settling ? 1500 : 5000);
    return () => clearInterval(timer);
  }, [settling, holding, load]);

  async function cancel() {
    if (!window.confirm("Cancel this order?")) return;
    setCancelling(true);
    try {
      setOrder(await api(`/api/v1/orders/${encodeURIComponent(number)}/cancel/`, { method: "POST", body: {} }));
    } catch (err) {
      setError(err.message);
    } finally {
      setCancelling(false);
    }
  }

  if (!order) {
    return (
      <div className="py-24 text-center">
        <p className="text-ink-soft">{error || "Loading order…"}</p>
        {error && <Link href="/orders" className="mt-3 inline-block font-medium text-accent hover:underline">Back to your orders</Link>}
      </div>
    );
  }

  const reached = order.status === "cancelled" || order.status === "reserving" ? -1 : JOURNEY.indexOf(order.status);
  const address = order.shipping_address;
  const secondsLeft = order.hold_expires_at
    ? Math.max(0, Math.floor((new Date(order.hold_expires_at).getTime() - now) / 1000))
    : null;

  return (
    <div className="space-y-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Link href="/orders" className="text-sm font-medium text-accent hover:underline">Your orders</Link>
          <h1 className="mt-1 text-3xl font-extrabold sm:text-5xl">Order {order.number}</h1>
          <p className="mt-2 text-ink-soft">Placed {dateTime(order.created_at)}</p>
        </div>
        <StatusBadge status={order.status} />
      </div>

      {order.status === "reserving" && (
        <Notice tone="info">
          <span className="flex items-center gap-3">
            <span aria-hidden="true" className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-accent border-t-transparent" />
            Checking stock for your items. This usually takes a few seconds.
          </span>
        </Notice>
      )}

      {order.status === "pending_payment" && secondsLeft !== null && (
        <Notice tone="info">
          {secondsLeft > 0
            ? `Your items are held for you until ${dateTime(order.hold_expires_at)}, ${countdown(secondsLeft)} left. Pay before then or they go back on sale.`
            : "Your hold has run out. This order is being cancelled."}
        </Notice>
      )}

      {order.status !== "cancelled" && order.status !== "reserving" ? (
        <ol className="grid grid-cols-4 gap-3" aria-label="Order progress">
          {JOURNEY.map((step, index) => (
            <li key={step} className="text-sm" aria-current={index === reached ? "step" : undefined}>
              <span className="inset block h-3 overflow-hidden rounded-full p-0.5">
                <span className={`block h-full rounded-full ${index <= reached ? "bg-[image:var(--metal)]" : ""}`} />
              </span>
              <span className={`mt-2 block ${index <= reached ? "font-semibold" : "text-ink-soft"}`}>{orderStatus(step)}</span>
            </li>
          ))}
        </ol>
      ) : (
        <Notice tone="info">
          This order was cancelled.{order.cancellation?.detail ? ` ${order.cancellation.detail}` : ""}
        </Notice>
      )}

      {order.refund && <Notice tone="info">{refundText(order.refund)}</Notice>}

      <Notice>{error}</Notice>

      {order.status === "pending_payment" && <PaymentPanel order={order} onPaid={load} />}

      <div className="grid gap-8 md:grid-cols-[1fr_320px]">
        <section aria-labelledby="items-heading" className="raised p-6">
          <h2 id="items-heading" className="mb-5 text-2xl font-bold">Items</h2>
          <ul className="space-y-4">
            {order.items.map((item) => (
              <li key={item.sku} className="flex items-center gap-4">
                <div className="inset h-20 w-20 shrink-0 overflow-hidden">
                  {item.thumbnail && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={item.thumbnail} alt="" className="photo h-full w-full object-cover" />
                  )}
                </div>
                <div className="flex flex-1 flex-wrap items-center justify-between gap-3">
                  <div>
                    <Link href={`/products/${item.product_slug}`} className="font-semibold hover:text-accent">{item.product_name}</Link>
                    <p className="text-sm text-ink-soft">
                      {[variantLabel(item), `${item.quantity} × ${money(item.unit_price)}`].filter(Boolean).join(", ")}
                    </p>
                  </div>
                  <LinePrice price={item.line_total} />
                </div>
              </li>
            ))}
          </ul>
          <dl className="ml-auto mt-6 max-w-xs space-y-2 border-t border-line pt-5">
            <div className="flex justify-between"><dt>Items</dt><dd>{money(order.subtotal)}</dd></div>
            <div className="flex justify-between">
              <dt>Delivery</dt>
              <dd className={Number(order.shipping_fee) === 0 ? "font-semibold text-accent" : ""}>
                {Number(order.shipping_fee) === 0 ? "Free" : money(order.shipping_fee)}
              </dd>
            </div>
            <div className="flex justify-between pt-2 font-display text-2xl font-extrabold"><dt>Total</dt><dd>{money(order.total)}</dd></div>
          </dl>
        </section>

        <aside className="space-y-8">
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

          {order.can_cancel && order.status === "pending_payment" && (
            <Button variant="danger" onClick={cancel} busy={cancelling} className="w-full">
              {cancelling ? "Cancelling…" : "Cancel order"}
            </Button>
          )}
        </aside>
      </div>
    </div>
  );
}

export default function OrderPage() {
  return (
    <RequireSignIn>
      <OrderDetail />
    </RequireSignIn>
  );
}
