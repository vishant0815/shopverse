import Link from "next/link";

import { GlassPrice } from "./Price";

export default function ProductTile({ product }) {
  return (
    <Link href={`/products/${product.slug}`} className="raised lift group block p-3.5">
      <div className="inset relative aspect-square overflow-hidden">
        {product.thumbnail ? (
          // Plain <img>: images come from any seller's host, so next/image domain rules don't fit.
          // eslint-disable-next-line @next/next/no-img-element
          <img src={product.thumbnail} alt="" loading="lazy" className="photo h-full w-full object-cover" />
        ) : null}
        {product.discount_percent > 0 && (
          <span className="off-pill absolute right-2.5 top-2.5 text-xs">−{product.discount_percent}%</span>
        )}
        <GlassPrice price={product.min_price} was={product.compare_at_price} className="absolute bottom-2.5 left-2.5" />
      </div>
      <div className="px-1 pb-1 pt-3.5">
        <p className="text-sm text-ink-soft">{product.brand}</p>
        <h3 className="font-sans text-base font-semibold leading-snug group-hover:text-accent">{product.name}</h3>
      </div>
    </Link>
  );
}
