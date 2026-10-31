"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import PaymentPanel from "@/components/PaymentPanel";
import RequireSignIn from "@/components/RequireSignIn";
import StatusBadge from "@/components/StatusBadge";
import { Button, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTime, money, orderStatus, variantLabel } from "@/lib/format";

const JOURNEY = ["pending_payment", "paid", "shipped", "delivered"];

function OrderDetail() {
  const { number } = useParams();
  const [order, setOrder] = useState(null);
  const [error, setError] = useState("");
  const [cancelling, setCancelling] = useState(false);

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
        {error && <Link href="/orders" className="mt-3 inline-block text-cobalt hover:underline">Back to your orders</Link>}
      </div>
    );
  }

  const reached = order.status === "cancelled" ? -1 : JOURNEY.indexOf(order.status);
  const address = order.shipping_address;

  return (
    <div className="space-y-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Link href="/orders" className="text-sm text-cobalt hover:underline">Your orders</Link>
          <h1 className="mt-1 text-4xl font-extrabold">Order {order.number}</h1>
          <p className="mt-1 text-ink-soft">Placed {dateTime(order.created_at)}</p>
        </div>
        <StatusBadge status={order.status} />
      </div>

      {order.status !== "cancelled" ? (
        <ol className="grid grid-cols-4 gap-2" aria-label="Order progress">
          {JOURNEY.map((step, index) => (
            <li key={step} className={`border-t-4 pt-2 text-sm ${index <= reached ? "border-cobalt font-semibold" : "border-line text-ink-soft"}`}>
              {orderStatus(step)}
            </li>
          ))}
        </ol>
      ) : (
        <Notice tone="info">This order was cancelled.</Notice>
      )}

      <Notice>{error}</Notice>

      {order.status === "pending_payment" && <PaymentPanel order={order} onPaid={load} />}

      <div className="grid gap-10 md:grid-cols-[1fr_300px]">
        <section aria-labelledby="items-heading">
          <h2 id="items-heading" className="mb-4 text-2xl font-bold">Items</h2>
          <ul className="divide-y divide-line border-y border-line">
            {order.items.map((item) => (
              <li key={item.sku} className="flex gap-4 py-4">
                <div className="h-20 w-20 shrink-0 overflow-hidden rounded-sm bg-shelf">
                  {item.thumbnail && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={item.thumbnail} alt="" className="h-full w-full object-cover mix-blend-multiply" />
                  )}
                </div>
                <div className="flex flex-1 justify-between gap-4">
                  <div>
                    <Link href={`/products/${item.product_slug}`} className="font-semibold hover:text-cobalt">{item.product_name}</Link>
                    <p className="text-sm text-ink-soft">
                      {[variantLabel(item), `${item.quantity} × ${money(item.unit_price)}`].filter(Boolean).join(", ")}
                    </p>
                  </div>
                  <span className="font-semibold">{money(item.line_total)}</span>
                </div>
              </li>
            ))}
          </ul>
          <dl className="ml-auto mt-4 max-w-xs space-y-1">
            <div className="flex justify-between"><dt>Items</dt><dd>{money(order.subtotal)}</dd></div>
            <div className="flex justify-between">
              <dt>Delivery</dt><dd>{Number(order.shipping_fee) === 0 ? "Free" : money(order.shipping_fee)}</dd>
            </div>
            <div className="flex justify-between border-t border-line pt-2 text-lg font-bold"><dt>Total</dt><dd>{money(order.total)}</dd></div>
          </dl>
        </section>

        <aside className="space-y-8">
          <section aria-labelledby="address-heading">
            <h2 id="address-heading" className="mb-2 text-xl font-bold">Delivering to</h2>
            <address className="not-italic leading-relaxed text-ink-soft">
              {address.full_name}<br />
              {address.line1}<br />
              {address.line2 && <>{address.line2}<br /></>}
              {address.city} {address.postcode}<br />
              {address.phone}
            </address>
          </section>

          <section aria-labelledby="history-heading">
            <h2 id="history-heading" className="mb-2 text-xl font-bold">History</h2>
            <ol className="space-y-3 border-l-2 border-line pl-4 text-sm">
              {order.history.map((entry, index) => (
                <li key={index}>
                  <span className="font-semibold">{orderStatus(entry.to_status)}</span>
                  <span className="block text-ink-soft">{dateTime(entry.created_at)}{entry.note ? `: ${entry.note}` : ""}</span>
                </li>
              ))}
            </ol>
          </section>

          {/* Refunds aren't automated yet, so the site only offers cancelling before payment. */}
          {order.can_cancel && order.status === "pending_payment" && (
            <Button variant="danger" onClick={cancel} busy={cancelling}>
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
