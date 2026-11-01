import { money } from "@/lib/format";

// Frosted-glass price chip that sits on a product photo.
export function GlassPrice({ price, was, className = "" }) {
  const onSale = was && Number(was) > Number(price);
  return (
    <span className={`glass-chip ${className}`}>
      <span className="now">{money(price)}</span>
      {onSale && (
        <>
          <span className="was text-xs">{money(was)}</span>
          <span className="sr-only">, reduced from {money(was)}</span>
        </>
      )}
    </span>
  );
}

// Big price in a pressed-in panel, for the product page.
export function PricePanel({ price, was, discount }) {
  const onSale = was && Number(was) > Number(price);
  return (
    <div className="inset inline-flex flex-wrap items-center gap-4 rounded-[18px] py-3 pl-6 pr-4">
      <span className="metal-text font-display text-[2.75rem] font-extrabold leading-none tracking-tight">{money(price)}</span>
      {onSale && <span className="was text-xl">{money(was)}</span>}
      {onSale && discount > 0 && <span className="off-pill text-sm">{discount}% off</span>}
      {onSale && <span className="sr-only">Reduced from {money(was)}</span>}
    </div>
  );
}

// Small pressed-in price, for basket and order lines.
export function LinePrice({ price }) {
  return (
    <span className="inset whitespace-nowrap rounded-xl px-3.5 py-2 font-display text-lg font-extrabold">
      <span className="metal-text">{money(price)}</span>
    </span>
  );
}
