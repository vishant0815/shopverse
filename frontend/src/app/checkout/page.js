"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import AddressForm, { emptyAddress } from "@/components/AddressForm";
import RequireSignIn from "@/components/RequireSignIn";
import { Button, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { money, variantLabel } from "@/lib/format";
import { useSession } from "@/lib/session";

const ADDRESS_FIELDS = ["full_name", "phone", "line1", "line2", "city", "county", "postcode", "country"];

function pick(address) {
  return Object.fromEntries(ADDRESS_FIELDS.map((key) => [key, address[key] || ""]));
}

function Checkout() {
  const router = useRouter();
  const { user, refreshCart } = useSession();
  const [cart, setCart] = useState(null);
  const [addresses, setAddresses] = useState([]);
  const [choice, setChoice] = useState("new");
  const [draft, setDraft] = useState(() => ({ ...emptyAddress, full_name: "" }));
  const [saveAddress, setSaveAddress] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState({});
  // One key per visit to this page. If the request is sent twice (double-click,
  // flaky network), the orders service returns the same order instead of a second one.
  const [idempotencyKey] = useState(() => crypto.randomUUID());

  useEffect(() => {
    (async () => {
      try {
        const [cartData, addressData] = await Promise.all([api("/api/v1/cart/"), api("/api/v1/addresses/")]);
        setCart(cartData);
        setAddresses(addressData.results);
        const preferred = addressData.results.find((a) => a.is_default) || addressData.results[0];
        if (preferred) setChoice(preferred.id);
        setDraft((d) => ({ ...d, full_name: [user.first_name, user.last_name].filter(Boolean).join(" ") }));
      } catch (err) {
        setError(err.message);
      }
    })();
  }, [user]);

  async function placeOrder(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setFieldErrors({});
    const shippingAddress = choice === "new" ? pick(draft) : pick(addresses.find((a) => a.id === choice));

    try {
      if (choice === "new" && saveAddress) {
        try {
          const saved = await api("/api/v1/addresses/", { method: "POST", body: shippingAddress });
          // Select the saved address so a retry (e.g. after a price change) doesn't save it twice.
          setAddresses((list) => [...list, saved]);
          setChoice(saved.id);
        } catch (err) {
          if (err.status === 400) {
            setFieldErrors(Object.fromEntries(Object.entries(err.data).map(([k, v]) => [k, [].concat(v).join(" ")])));
            setBusy(false);
            return;
          }
          // Saving the address is a convenience; don't block the order if it fails.
        }
      }
      const order = await api("/api/v1/checkout/", {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        // The total the customer is looking at. If a price changed meanwhile, checkout stops.
        body: { shipping_address: shippingAddress, expected_total: cart.total },
      });
      await refreshCart();
      router.push(`/orders/${order.number}`);
    } catch (err) {
      if (err.code === "price_changed") {
        setCart(await api("/api/v1/cart/"));
        setError("A price changed since you opened this page. Check the new total, then place your order again.");
      } else if (err.code === "items_unavailable") {
        setError("Some items in your basket are no longer available. Remove them from your basket, then try again.");
      } else if (err.status === 400 && err.data?.shipping_address) {
        setFieldErrors(Object.fromEntries(Object.entries(err.data.shipping_address).map(([k, v]) => [k, [].concat(v).join(" ")])));
      } else {
        setError(err.message);
      }
    } finally {
      setBusy(false);
    }
  }

  if (!cart) return <p className="py-24 text-center text-ink-soft">{error || "Loading checkout…"}</p>;
  if (!cart.items.length) {
    return (
      <div className="py-20 text-center">
        <h1 className="text-3xl font-bold">Nothing to check out</h1>
        <Link href="/products" className="mt-4 inline-block text-cobalt hover:underline">Browse products</Link>
      </div>
    );
  }

  return (
    <form onSubmit={placeOrder} className="grid gap-10 lg:grid-cols-[1fr_340px]">
      <section aria-labelledby="delivery-heading">
        <h1 className="mb-6 text-4xl font-extrabold">Checkout</h1>
        <h2 id="delivery-heading" className="mb-4 text-2xl font-bold">Delivery address</h2>
        <div className="space-y-3">
          {addresses.map((address) => (
            <label
              key={address.id}
              className={`flex cursor-pointer gap-3 border p-4 ${choice === address.id ? "border-ink bg-white" : "border-line"}`}
            >
              <input
                type="radio"
                name="address"
                checked={choice === address.id}
                onChange={() => setChoice(address.id)}
                className="mt-1 accent-cobalt"
              />
              <span>
                <span className="font-semibold">{address.full_name}</span>
                <span className="block text-ink-soft">
                  {[address.line1, address.line2, address.city, address.postcode].filter(Boolean).join(", ")}
                </span>
              </span>
            </label>
          ))}
          <label className={`flex cursor-pointer gap-3 border p-4 ${choice === "new" ? "border-ink bg-white" : "border-line"}`}>
            <input type="radio" name="address" checked={choice === "new"} onChange={() => setChoice("new")} className="mt-1 accent-cobalt" />
            <span className="font-semibold">{addresses.length ? "Use a new address" : "New address"}</span>
          </label>
        </div>

        {choice === "new" && (
          <div className="mt-6 space-y-4">
            <AddressForm value={draft} onChange={setDraft} errors={fieldErrors} />
            <label className="flex items-center gap-3 text-sm">
              <input type="checkbox" checked={saveAddress} onChange={(e) => setSaveAddress(e.target.checked)} className="h-4 w-4 accent-cobalt" />
              Save this address for next time
            </label>
          </div>
        )}
      </section>

      <aside aria-label="Order summary" className="h-fit border border-ink bg-white p-6">
        <h2 className="text-xl font-bold">Your order</h2>
        <ul className="mt-4 space-y-3 text-sm">
          {cart.items.map((item) => (
            <li key={item.variant_id} className="flex justify-between gap-3">
              <span>
                {item.quantity} × {item.product_name}
                <span className="block text-ink-soft">{variantLabel(item)}</span>
              </span>
              <span className="shrink-0">{money(item.line_total)}</span>
            </li>
          ))}
        </ul>
        <dl className="mt-4 space-y-2 border-t border-line pt-4">
          <div className="flex justify-between"><dt>Items</dt><dd>{money(cart.subtotal)}</dd></div>
          <div className="flex justify-between">
            <dt>Delivery</dt><dd>{Number(cart.shipping_fee) === 0 ? "Free" : money(cart.shipping_fee)}</dd>
          </div>
          <div className="flex justify-between border-t border-line pt-3 text-lg font-bold">
            <dt>Total</dt><dd>{money(cart.total)}</dd>
          </div>
        </dl>
        <div className="mt-4"><Notice>{error}</Notice></div>
        <Button type="submit" busy={busy} disabled={!cart.prices_available} className="mt-6 w-full py-3 text-lg">
          {busy ? "Placing order…" : "Place order"}
        </Button>
        <p className="mt-3 text-sm text-ink-soft">You&apos;ll pay on the next page.</p>
      </aside>
    </form>
  );
}

export default function CheckoutPage() {
  return (
    <RequireSignIn>
      <Checkout />
    </RequireSignIn>
  );
}
