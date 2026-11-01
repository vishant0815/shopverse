"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { LinePrice } from "@/components/Price";
import RequireSignIn from "@/components/RequireSignIn";
import { Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { money, variantLabel } from "@/lib/format";
import { useSession } from "@/lib/session";

const MAX_QUANTITY = 10;

function Basket() {
  const { refreshCart } = useSession();
  const [cart, setCart] = useState(null);
  const [error, setError] = useState("");
  const [busyItem, setBusyItem] = useState(null);

  const load = useCallback(async () => {
    try {
      setCart(await api("/api/v1/cart/"));
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function change(variantId, request) {
    setBusyItem(variantId);
    setError("");
    try {
      setCart(await api(`/api/v1/cart/items/${variantId}/`, request));
      await refreshCart();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyItem(null);
    }
  }

  const setQuantity = (item, quantity) =>
    change(item.variant_id, { method: "PATCH", body: { quantity } });

  if (!cart) return <p className="py-24 text-center text-ink-soft">{error || "Loading your basket…"}</p>;

  if (!cart.items.length) {
    return (
      <div className="raised mx-auto max-w-md px-8 py-16 text-center">
        <h1 className="text-4xl font-extrabold">Your basket is empty</h1>
        <p className="mt-3 text-ink-soft">Things you add will wait here until you check out.</p>
        <Link href="/products" className="btn btn-metal mt-8">Browse products</Link>
      </div>
    );
  }

  return (
    <div className="grid gap-10 lg:grid-cols-[1fr_340px]">
      <section aria-labelledby="basket-heading">
        <h1 id="basket-heading" className="mb-8 text-4xl font-extrabold sm:text-5xl">Basket</h1>
        <div className="mb-6 space-y-4 empty:hidden">
          <Notice>{error}</Notice>
          {!cart.prices_available && (
            <Notice tone="info">Prices can&apos;t be loaded right now. Your items are safe; try again shortly.</Notice>
          )}
          {cart.unavailable_variant_ids?.length > 0 && (
            <Notice>
              {cart.unavailable_variant_ids.length === 1 ? "One item is" : "Some items are"} no longer available
              and won&apos;t be included at checkout.{" "}
              {cart.unavailable_variant_ids.map((id) => (
                <button key={id} onClick={() => change(id, { method: "DELETE" })} className="font-semibold underline">
                  Remove
                </button>
              ))}
            </Notice>
          )}
        </div>

        <ul className="space-y-6">
          {cart.items.map((item) => {
            const busy = busyItem === item.variant_id;
            return (
              <li key={item.variant_id} className="raised flex items-center gap-5 p-4" aria-busy={busy || undefined}>
                <div className="inset h-24 w-24 shrink-0 overflow-hidden">
                  {item.thumbnail && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={item.thumbnail} alt="" className="photo h-full w-full object-cover" />
                  )}
                </div>
                <div className="flex flex-1 flex-wrap items-center justify-between gap-4">
                  <div>
                    {item.product_slug ? (
                      <Link href={`/products/${item.product_slug}`} className="font-semibold hover:text-accent">{item.product_name}</Link>
                    ) : (
                      <span className="font-semibold">Item</span>
                    )}
                    <p className="text-sm text-ink-soft">{variantLabel(item)}</p>
                    <div className="mt-3 flex items-center gap-4">
                      <div className="inset flex items-center rounded-xl" role="group" aria-label={`Quantity of ${item.product_name}`}>
                        <button className="px-3 py-1 text-lg text-ink-soft hover:text-accent disabled:opacity-40" aria-label="One fewer"
                          disabled={busy || item.quantity <= 1} onClick={() => setQuantity(item, item.quantity - 1)}>−</button>
                        <span className="min-w-5 text-center font-bold" aria-live="polite">{item.quantity}</span>
                        <button className="px-3 py-1 text-lg text-ink-soft hover:text-accent disabled:opacity-40" aria-label="One more"
                          disabled={busy || item.quantity >= MAX_QUANTITY} onClick={() => setQuantity(item, item.quantity + 1)}>+</button>
                      </div>
                      <button onClick={() => change(item.variant_id, { method: "DELETE" })} disabled={busy}
                        className="text-sm font-semibold text-power hover:underline">
                        Remove
                      </button>
                    </div>
                  </div>
                  {item.line_total && <LinePrice price={item.line_total} />}
                </div>
              </li>
            );
          })}
        </ul>
      </section>

      {cart.prices_available && (
        <aside aria-label="Order summary" className="raised h-fit p-6 lg:mt-[5.25rem]">
          <h2 className="text-2xl font-bold">Summary</h2>
          <dl className="mt-5 space-y-3">
            <div className="flex justify-between"><dt>Items</dt><dd>{money(cart.subtotal)}</dd></div>
            <div className="flex justify-between">
              <dt>Delivery</dt>
              <dd className={Number(cart.shipping_fee) === 0 ? "font-semibold text-accent" : ""}>
                {Number(cart.shipping_fee) === 0 ? "Free" : money(cart.shipping_fee)}
              </dd>
            </div>
            <div className="flex justify-between border-t border-line pt-4 font-display text-2xl font-extrabold">
              <dt>Total</dt><dd>{money(cart.total)}</dd>
            </div>
          </dl>
          <Link href="/checkout" className="btn btn-metal mt-6 w-full py-3.5 text-lg">Check out</Link>
        </aside>
      )}
    </div>
  );
}

export default function CartPage() {
  return (
    <RequireSignIn>
      <Basket />
    </RequireSignIn>
  );
}
