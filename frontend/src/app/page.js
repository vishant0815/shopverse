import Link from "next/link";

import CatalogueUnavailable from "@/components/CatalogueUnavailable";
import ProductTile from "@/components/ProductTile";
import { CatalogueDown, getCategoryTree, getProducts } from "@/lib/catalog-server";

// Render on each request (the API calls are still cached for a short time). Without this the
// page would be pre-built during `next build`, when the backend usually isn't running.
export const dynamic = "force-dynamic";

function countCategories(nodes) {
  return nodes.reduce((total, node) => total + 1 + countCategories(node.children || []), 0);
}

export default async function HomePage() {
  let tree, newest, featured, onSale;
  try {
    [tree, newest, featured, onSale] = await Promise.all([
      getCategoryTree(),
      getProducts({ ordering: "-created_at", page_size: 8 }),
      // Featured: the four highest-priced products, shown beside the headline.
      getProducts({ ordering: "-min_price", page_size: 4 }),
      getProducts({ on_sale: "true", page_size: 1 }),
    ]);
  } catch (error) {
    if (error instanceof CatalogueDown) return <CatalogueUnavailable />;
    throw error;
  }

  const stats = [
    { value: newest.count, label: "products" },
    { value: countCategories(tree), label: "categories" },
  ];

  return (
    <div className="space-y-20">
      <section className="grid items-center gap-12 md:grid-cols-[1.05fr_1fr]">
        <div>
          <h1 className="text-5xl font-extrabold sm:text-7xl">
            <span className="rise block">Lots of sellers.</span>
            <span className="rise rise-2 metal-text block pb-1">One basket.</span>
          </h1>
          <p className="mt-6 max-w-md text-lg leading-relaxed text-ink-soft">
            Phones, clothes and things for the home from independent sellers, paid for in one checkout.
          </p>
          <div className="mt-8 flex flex-wrap gap-4">
            {tree.map((category) => (
              <Link key={category.slug} href={`/products?category=${category.slug}`} className="raised-sm px-5 py-3 font-semibold hover:text-accent">
                {category.name}
              </Link>
            ))}
          </div>
          <dl className="mt-10 flex flex-wrap gap-x-9 gap-y-4 text-sm text-ink-soft">
            {stats.map((stat) => (
              <div key={stat.label} className="flex flex-col-reverse">
                <dt>{stat.label}</dt>
                <dd className="font-display text-3xl font-extrabold text-ink">{stat.value}</dd>
              </div>
            ))}
            {onSale.count > 0 && (
              <div className="flex flex-col-reverse">
                <dt>
                  <Link href="/products?on_sale=true" className="hover:underline">on sale now</Link>
                </dt>
                <dd className="font-display text-3xl font-extrabold text-power">{onSale.count}</dd>
              </div>
            )}
          </dl>
        </div>

        <div className="grid grid-cols-2 gap-5 sm:gap-6">
          {featured.results.map((product) => (
            <ProductTile key={product.id} product={product} />
          ))}
        </div>
      </section>

      <section>
        <div className="mb-7 flex items-baseline justify-between">
          <h2 className="text-4xl font-bold">New in</h2>
          <Link href="/products" className="font-semibold text-accent hover:underline">See everything</Link>
        </div>
        <div className="grid grid-cols-2 gap-5 sm:gap-7 md:grid-cols-4">
          {newest.results.map((product) => (
            <ProductTile key={product.id} product={product} />
          ))}
        </div>
      </section>

      <section className="grid gap-6 sm:grid-cols-3">
        {tree.map((category) => (
          <div key={category.slug} className="raised p-6">
            <h2 className="text-xl font-bold">
              <Link href={`/products?category=${category.slug}`} className="hover:text-accent">{category.name}</Link>
            </h2>
            <ul className="mt-3 space-y-1.5 text-ink-soft">
              {category.children.map((child) => (
                <li key={child.slug}>
                  <Link href={`/products?category=${child.slug}`} className="hover:text-accent">{child.name}</Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </section>
    </div>
  );
}
