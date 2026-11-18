"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api";
import { tracker } from "@/lib/clickstream";
import { discountPercent, minDefined, remainingLabel, remainingUnits } from "@/lib/flashSale";
import { useSession } from "@/lib/session";

import FlashCountdown from "./FlashCountdown";
import { PricePanel } from "./Price";
import { Button, Notice } from "./ui";

const MAX_QUANTITY = 10;
// Below this many left, the page says so, to nudge a shopper who is still deciding.
const LOW_STOCK = 5;

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

export default function AddToBasket({ variants, stock = {}, productId }) {
  const { user, refreshCart } = useSession();
  const router = useRouter();
  const pathname = usePathname();

  const colours = unique(variants.map((v) => v.colour));
  const sizes = unique(variants.map((v) => v.size));
  // Start on an option that can be bought, not on a sold-out one.
  const opening = variants.find((v) => stock[v.id] !== 0) || variants[0];
  const [colour, setColour] = useState(opening?.colour || "");
  const [size, setSize] = useState(opening?.size || "");
  const [quantity, setQuantity] = useState(1);
  const [state, setState] = useState({ busy: false, error: "", added: false });

  const selected = useMemo(
    () => variants.find((v) => (v.colour || "") === colour && (v.size || "") === size),
    [variants, colour, size],
  );
  // Units sold at each flash sale price on this product, from the orders service. Empty while loading.
  const [sold, setSold] = useState({});
  const flashItemIds = useMemo(() => variants.map((v) => v.flash_sale?.item_id).filter(Boolean), [variants]);
  useEffect(() => {
    if (!flashItemIds.length) return;
    api(`/api/v1/flash-sales/sold/?items=${flashItemIds.join(",")}`)
      .then((data) => setSold(data.results))
      .catch(() => setSold({})); // the cap is still enforced at checkout if this count is missing
  }, [flashItemIds]);

  // undefined means "not known", which is treated as available; only a real zero is sold out.
  const flash = selected?.flash_sale || null;
  const flashLeft = flash?.quantity_cap ? remainingUnits(flash.quantity_cap, sold[flash.item_id]) : undefined;
  const left = minDefined(selected ? stock[selected.id] : undefined, flashLeft);
  const soldOut = (variant) => stock[variant.id] === 0;
  const maxQuantity = left === undefined ? MAX_QUANTITY : Math.min(MAX_QUANTITY, left);
  const sizeAvailable = (option) => variants.some(
    (v) => (v.colour || "") === colour && v.size === option && !soldOut(v),
  );

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
      await api("/api/v1/cart/items/", { method: "POST", body: { variant_id: selected.id, quantity: Math.min(quantity, maxQuantity) } });
      tracker().track("add_to_cart", { product_id: productId, variant_id: selected.id, quantity: Math.min(quantity, maxQuantity) });
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
        <div className="space-y-4">
          {flash && <FlashCountdown endsAt={flash.ends_at} />}
          <PricePanel
            price={flash ? flash.sale_price : selected.price}
            was={flash ? selected.price : selected.compare_at_price}
            discount={flash ? discountPercent(selected.price, flash.sale_price) : selected.discount_percent}
          />
        </div>
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
            onClick={() => setQuantity((q) => Math.min(maxQuantity, q + 1))} disabled={quantity >= maxQuantity} aria-label="One more">+</button>
        </div>
        <Button onClick={add} busy={state.busy} disabled={!selected || left === 0} className="flex-1 py-3.5 text-lg">
          {left === 0 ? "Sold out" : state.busy ? "Adding…" : "Add to basket"}
        </Button>
      </div>

      {left !== undefined && left > 0 && left <= LOW_STOCK && (
        <p className="font-semibold text-power">Only {left} left in this size.</p>
      )}

      {flash?.quantity_cap && (
        <div>
          <p className="mb-2 text-sm font-semibold">{remainingLabel(flashLeft)}</p>
          <div
            role="progressbar"
            aria-label="Sale stock sold"
            aria-valuemin={0}
            aria-valuemax={flash.quantity_cap}
            aria-valuenow={Math.min(sold[flash.item_id] ?? 0, flash.quantity_cap)}
            className="inset h-2.5 overflow-hidden rounded-full"
          >
            <div
              className="h-full bg-accent"
              style={{ width: `${Math.min(100, Math.round(((sold[flash.item_id] ?? 0) / flash.quantity_cap) * 100))}%` }}
            />
          </div>
        </div>
      )}

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
