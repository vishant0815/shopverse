"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

import { PricePanel } from "./Price";
import { Button, Notice } from "./ui";

const MAX_QUANTITY = 10;

function unique(values) {
  return [...new Set(values.filter(Boolean))];
}

function OptionButton({ selected, disabled, onClick, children }) {
  return (
    <button
      type="button"
      disabled={disabled}
      aria-pressed={selected}
      onClick={onClick}
      className={`raised-sm min-w-14 px-4 py-2.5 font-medium ${selected ? "pressed" : "hover:text-accent"} disabled:cursor-not-allowed disabled:text-ink-soft disabled:line-through disabled:opacity-45`}
    >
      {children}
    </button>
  );
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

  const changed = () => setState((s) => ({ ...s, added: false }));

  return (
    <div className="mt-6 space-y-7">
      {selected ? (
        <PricePanel price={selected.price} was={selected.compare_at_price} discount={selected.discount_percent} />
      ) : (
        <p className="text-ink-soft">That combination isn&apos;t available. Pick another size.</p>
      )}

      {colours.length > 0 && (
        <fieldset>
          <legend className="mb-3 font-semibold">Colour: <span className="font-normal text-ink-soft">{colour}</span></legend>
          <div className="flex flex-wrap gap-3.5">
            {colours.map((option) => (
              <OptionButton
                key={option}
                selected={colour === option}
                onClick={() => {
                  setColour(option);
                  if (!variants.some((v) => v.colour === option && v.size === size)) {
                    setSize(variants.find((v) => v.colour === option)?.size || "");
                  }
                  changed();
                }}
              >
                {option}
              </OptionButton>
            ))}
          </div>
        </fieldset>
      )}

      {sizes.length > 0 && (
        <fieldset>
          <legend className="mb-3 font-semibold">Size: <span className="font-normal text-ink-soft">{size}</span></legend>
          <div className="flex flex-wrap gap-3.5">
            {sizes.map((option) => (
              <OptionButton
                key={option}
                selected={size === option}
                disabled={!sizeAvailable(option)}
                onClick={() => {
                  setSize(option);
                  changed();
                }}
              >
                {option}
              </OptionButton>
            ))}
          </div>
        </fieldset>
      )}

      <div className="flex flex-wrap items-stretch gap-4">
        <div className="inset flex items-center" role="group" aria-label="Quantity">
          <button type="button" className="h-full px-4 text-xl text-ink-soft hover:text-accent disabled:opacity-40"
            onClick={() => setQuantity((q) => Math.max(1, q - 1))} disabled={quantity <= 1} aria-label="One fewer">−</button>
          <span className="min-w-6 text-center font-bold" aria-live="polite">{quantity}</span>
          <button type="button" className="h-full px-4 text-xl text-ink-soft hover:text-accent disabled:opacity-40"
            onClick={() => setQuantity((q) => Math.min(MAX_QUANTITY, q + 1))} disabled={quantity >= MAX_QUANTITY} aria-label="One more">+</button>
        </div>
        <Button onClick={add} busy={state.busy} disabled={!selected} className="flex-1 py-3.5 text-lg">
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
