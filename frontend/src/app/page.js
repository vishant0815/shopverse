import Link from "next/link";

import CatalogueUnavailable from "@/components/CatalogueUnavailable";
import ProductTile from "@/components/ProductTile";
import { CatalogueDown, getCategoryTree, getProducts } from "@/lib/catalog-server";

// Render on each request (the API calls are still cached for a short time). Without this the
// page would be pre-built during `next build`, when the backend usually isn't running.
export const dynamic = "force-dynamic";

export default async function HomePage() {
  let tree, newest, featured;
  try {
    [tree, newest, featured] = await Promise.all([
      getCategoryTree(),
      getProducts({ ordering: "-created_at", page_size: 8 }),
      // Featured: the four highest-priced products, shown beside the headline.
      getProducts({ ordering: "-min_price", page_size: 4 }),
    ]);
  } catch (error) {
    if (error instanceof CatalogueDown) return <CatalogueUnavailable />;
    throw error;
  }

  return (
    <div className="space-y-16">
      <section className="grid items-center gap-10 md:grid-cols-[1.1fr_1fr]">
        <div>
          <h1 className="text-5xl font-extrabold sm:text-6xl">
            Lots of sellers.
            <br />
            One basket.
          </h1>
          <p className="mt-5 max-w-md text-lg text-ink-soft">
            Phones, clothes and things for the home from independent sellers, paid for in one checkout.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            {tree.map((category) => (
              <Link
                key={category.slug}
                href={`/products?category=${category.slug}`}
                className="rounded-sm border border-ink px-4 py-2 font-medium hover:bg-ink hover:text-white"
              >
                {category.name}
              </Link>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          {featured.results.map((product) => (
            <ProductTile key={product.id} product={product} />
          ))}
        </div>
      </section>

      <section>
        <div className="mb-6 flex items-baseline justify-between">
          <h2 className="text-3xl font-bold">New in</h2>
          <Link href="/products" className="font-medium text-cobalt hover:underline">See everything</Link>
        </div>
        <div className="grid grid-cols-2 gap-x-5 gap-y-8 md:grid-cols-4">
          {newest.results.map((product) => (
            <ProductTile key={product.id} product={product} />
          ))}
        </div>
      </section>

      <section className="grid gap-8 border-t border-line pt-10 sm:grid-cols-3">
        {tree.map((category) => (
          <div key={category.slug}>
            <h2 className="text-xl font-bold">
              <Link href={`/products?category=${category.slug}`} className="hover:text-cobalt">{category.name}</Link>
            </h2>
            <ul className="mt-3 space-y-1.5 text-ink-soft">
              {category.children.map((child) => (
                <li key={child.slug}>
                  <Link href={`/products?category=${child.slug}`} className="hover:text-cobalt">{child.name}</Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </section>
    </div>
  );
}
