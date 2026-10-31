"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

import PriceTag from "./PriceTag";
import { Button, Notice } from "./ui";

function unique(values) {
  return [...new Set(values.filter(Boolean))];
}

export default function AddToBasket({ variants }) {
  const { user, refreshCart } = useSession();
  const router = useRouter();
  const pathname = usePathname();

  const colours = unique(variants.map((v) => v.colour));
  const sizes = unique(variants.map((v) => v.size));
  const [colour, setColour] = useState(colours[0] || "");
  const [size, setSize] = useState(
    variants.find((v) => (v.colour || "") === (colours[0] || ""))?.size || sizes[0] || "",
  );
  const [quantity, setQuantity] = useState(1);
  const [state, setState] = useState({ busy: false, error: "", added: false });

  const selected = useMemo(
    () => variants.find((v) => (v.colour || "") === colour && (v.size || "") === size),
    [variants, colour, size],
  );
  const sizeAvailable = (option) => variants.some((v) => (v.colour || "") === colour && v.size === option);

  if (!variants.length) {
    return <p className="mt-6 text-ink-soft">This product isn&apos;t available to buy at the moment.</p>;
  }

  async function add() {
    if (!user) {
      router.push(`/login?next=${encodeURIComponent(pathname)}`);
      return;
    }
    setState({ busy: true, error: "", added: false });
    try {
      await api("/api/v1/cart/items/", { method: "POST", body: { variant_id: selected.id, quantity } });
      await refreshCart();
      setState({ busy: false, error: "", added: true });
    } catch (error) {
      setState({ busy: false, error: error.message, added: false });
    }
  }

  return (
    <div className="mt-6 space-y-6">
      <div className="-ml-1" key={selected?.id}>
        {selected ? (
          <div className="flex items-center gap-3">
            <PriceTag price={selected.price} was={selected.compare_at_price} size="lg" swing />
            {selected.discount_percent > 0 && <span className="sale-sticker">{selected.discount_percent}% off</span>}
          </div>
        ) : (
          <p className="text-ink-soft">That combination isn&apos;t available. Pick another size.</p>
        )}
      </div>

      {colours.length > 0 && (
        <fieldset>
          <legend className="mb-2 font-medium">Colour: <span className="font-normal">{colour}</span></legend>
          <div className="flex flex-wrap gap-2">
            {colours.map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={colour === option}
                onClick={() => {
                  setColour(option);
                  if (!variants.some((v) => v.colour === option && v.size === size)) {
                    setSize(variants.find((v) => v.colour === option)?.size || "");
                  }
                  setState((s) => ({ ...s, added: false }));
                }}
                className={`rounded-sm border px-4 py-2 ${colour === option ? "border-ink bg-ink text-white" : "border-line bg-white hover:border-ink"}`}
              >
                {option}
              </button>
            ))}
          </div>
        </fieldset>
      )}

      {sizes.length > 0 && (
        <fieldset>
          <legend className="mb-2 font-medium">Size: <span className="font-normal">{size}</span></legend>
          <div className="flex flex-wrap gap-2">
            {sizes.map((option) => {
              const available = sizeAvailable(option);
              return (
                <button
                  key={option}
                  type="button"
                  disabled={!available}
                  aria-pressed={size === option}
                  onClick={() => {
                    setSize(option);
                    setState((s) => ({ ...s, added: false }));
                  }}
                  className={`min-w-12 rounded-sm border px-3 py-2 ${
                    size === option ? "border-ink bg-ink text-white" : "border-line bg-white hover:border-ink"
                  } disabled:cursor-not-allowed disabled:text-ink-soft/50 disabled:line-through`}
                >
                  {option}
                </button>
              );
            })}
          </div>
        </fieldset>
      )}

      <div className="flex flex-wrap items-end gap-3">
        <label>
          <span className="mb-2 block font-medium">Quantity</span>
          <select
            value={quantity}
            onChange={(e) => setQuantity(Number(e.target.value))}
            className="rounded-sm border border-line bg-white px-3 py-2.5"
          >
            {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </label>
        <Button onClick={add} busy={state.busy} disabled={!selected} className="flex-1 py-3 text-lg">
          {state.busy ? "Adding…" : "Add to basket"}
        </Button>
      </div>

      {state.added && (
        <Notice tone="success">
          Added to your basket. <Link href="/cart" className="font-semibold underline">Go to basket</Link>
        </Notice>
      )}
      <Notice>{state.error}</Notice>
      {selected && <p className="text-sm text-ink-soft">Item code {selected.sku}</p>}
    </div>
  );
}
