import { money } from "@/lib/format";

export default function PriceTag({ price, was, size = "md", swing = false }) {
  const sizes = { sm: "text-base", md: "text-lg", lg: "text-3xl" };
  const onSale = was && Number(was) > Number(price);
  return (
    <span className={`price-tag ${sizes[size]} ${swing ? "tag-swing" : ""}`}>
      {onSale && <span className="was">{money(was)}</span>}
      <span>{money(price)}</span>
      {onSale && <span className="sr-only">, reduced from {money(was)}</span>}
    </span>
  );
}
