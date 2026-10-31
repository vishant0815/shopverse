"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import PriceTag from "@/components/PriceTag";
import RequireSignIn from "@/components/RequireSignIn";
import { Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { money, variantLabel } from "@/lib/format";
import { useSession } from "@/lib/session";

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

  if (!cart) return <p className="py-24 text-center text-ink-soft">{error || "Loading your basket…"}</p>;

  if (!cart.items.length) {
    return (
      <div className="mx-auto max-w-md py-20 text-center">
        <h1 className="text-4xl font-extrabold">Your basket is empty</h1>
        <p className="mt-3 text-ink-soft">Things you add will wait here until you check out.</p>
        <Link href="/products" className="mt-6 inline-block rounded-sm bg-cobalt px-5 py-2.5 font-semibold text-white hover:bg-cobalt-deep">
          Browse products
        </Link>
      </div>
    );
  }

  return (
    <div className="grid gap-10 lg:grid-cols-[1fr_320px]">
      <section aria-labelledby="basket-heading">
        <h1 id="basket-heading" className="mb-6 text-4xl font-extrabold">Basket</h1>
        <div className="space-y-4">
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

        <ul className="divide-y divide-line border-y border-line">
          {cart.items.map((item) => (
            <li key={item.variant_id} className="flex gap-4 py-5" aria-busy={busyItem === item.variant_id || undefined}>
              <div className="h-24 w-24 shrink-0 overflow-hidden rounded-sm bg-shelf">
                {item.thumbnail && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={item.thumbnail} alt="" className="h-full w-full object-cover mix-blend-multiply" />
                )}
              </div>
              <div className="flex flex-1 flex-wrap items-start justify-between gap-4">
                <div>
                  {item.product_slug ? (
                    <Link href={`/products/${item.product_slug}`} className="font-semibold hover:text-cobalt">{item.product_name}</Link>
                  ) : (
                    <span className="font-semibold">Item</span>
                  )}
                  <p className="text-sm text-ink-soft">{variantLabel(item)}</p>
                  <div className="mt-3 flex items-center gap-4">
                    <label className="flex items-center gap-2 text-sm">
                      <span>Qty</span>
                      <select
                        value={item.quantity}
                        disabled={busyItem === item.variant_id}
                        onChange={(e) => change(item.variant_id, { method: "PATCH", body: { quantity: Number(e.target.value) } })}
                        className="rounded-sm border border-line bg-white px-2 py-1"
                      >
                        {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
                          <option key={n} value={n}>{n}</option>
                        ))}
                      </select>
                    </label>
                    <button
                      onClick={() => change(item.variant_id, { method: "DELETE" })}
                      disabled={busyItem === item.variant_id}
                      className="text-sm text-cobalt hover:underline"
                    >
                      Remove
                    </button>
                  </div>
                </div>
                {item.line_total && <PriceTag price={item.line_total} size="sm" />}
              </div>
            </li>
          ))}
        </ul>
      </section>

      {cart.prices_available && (
        <aside aria-label="Order summary" className="h-fit border border-ink bg-white p-6">
          <h2 className="text-xl font-bold">Summary</h2>
          <dl className="mt-4 space-y-2">
            <div className="flex justify-between"><dt>Items</dt><dd>{money(cart.subtotal)}</dd></div>
            <div className="flex justify-between">
              <dt>Delivery</dt>
              <dd>{Number(cart.shipping_fee) === 0 ? "Free" : money(cart.shipping_fee)}</dd>
            </div>
            <div className="flex justify-between border-t border-line pt-3 text-lg font-bold">
              <dt>Total</dt><dd>{money(cart.total)}</dd>
            </div>
          </dl>
          <Link
            href="/checkout"
            className="mt-6 block rounded-sm bg-cobalt py-3 text-center text-lg font-semibold text-white hover:bg-cobalt-deep"
          >
            Check out
          </Link>
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
