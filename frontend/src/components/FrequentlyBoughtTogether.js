import Link from "next/link";

import { getBoughtTogether } from "@/lib/catalog-server";

// Products shoppers often bought in the same order as this one. Renders nothing when there are none.
export default async function FrequentlyBoughtTogether({ productId }) {
  const items = await getBoughtTogether(productId);
  if (items.length === 0) return null;

  return (
    <section aria-labelledby="bought-together-heading" className="mt-16">
      <h2 id="bought-together-heading" className="text-xl font-bold">Frequently bought together</h2>
      <ul className="mt-5 grid gap-5 sm:grid-cols-3">
        {items.map((item) => (
          <li key={item.product_id}>
            <Link href={`/products/${item.slug}`} className="raised block p-3 hover:text-accent">
              <div className="inset aspect-square overflow-hidden">
                {item.image_url && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={item.image_url} alt="" className="photo h-full w-full object-cover" />
                )}
              </div>
              <p className="mt-3 font-semibold">{item.name}</p>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
