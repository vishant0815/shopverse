import Link from "next/link";

import PriceTag from "./PriceTag";

export default function ProductTile({ product }) {
  return (
    <Link href={`/products/${product.slug}`} className="group block">
      <div className="relative aspect-square overflow-hidden rounded-sm bg-shelf">
        {product.thumbnail ? (
          // Plain <img>: images come from any seller's host, so next/image domain rules don't fit.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={product.thumbnail}
            alt=""
            loading="lazy"
            className="h-full w-full object-cover mix-blend-multiply transition-transform duration-300 group-hover:scale-[1.03]"
          />
        ) : null}
        <div className="absolute bottom-3 left-0">
          <PriceTag price={product.min_price} size="sm" />
        </div>
      </div>
      <div className="mt-3">
        <p className="text-sm text-ink-soft">{product.brand}</p>
        <h3 className="font-sans text-base font-medium leading-snug group-hover:text-cobalt">{product.name}</h3>
      </div>
    </Link>
  );
}
