import Link from "next/link";

import CatalogueUnavailable from "@/components/CatalogueUnavailable";
import ProductTile from "@/components/ProductTile";
import SortSelect from "@/components/SortSelect";
import { CatalogueDown, findCategory, getCategoryTree, getProducts } from "@/lib/catalog-server";

const FILTER_KEYS = ["category", "search", "brand", "min_price", "max_price", "colour", "size", "ordering", "page"];
const PAGE_SIZE = 12;

export async function generateMetadata({ searchParams }) {
  const { search } = await searchParams;
  return { title: search ? `Results for “${search}”` : "All products" };
}

function linkWith(params, changes) {
  const next = { ...params, ...changes };
  if (!("page" in changes)) delete next.page; // a new filter starts again from page 1
  const query = new URLSearchParams(Object.entries(next).filter(([, v]) => v));
  return `/products${query.toString() ? `?${query}` : ""}`;
}

export default async function ProductsPage({ searchParams }) {
  const raw = await searchParams;
  const params = Object.fromEntries(FILTER_KEYS.map((key) => [key, raw[key] || ""]).filter(([, v]) => v));

  let tree, data;
  try {
    [tree, data] = await Promise.all([getCategoryTree(), getProducts({ ...params, page_size: PAGE_SIZE })]);
  } catch (error) {
    if (error instanceof CatalogueDown) return <CatalogueUnavailable />;
    throw error;
  }
  // An out-of-range page comes back as 404 from the API.
  data = data || { count: 0, results: [], next: null, previous: null };

  const current = params.category ? findCategory(tree, params.category) : null;
  const page = Number(params.page || 1);
  const pages = Math.max(1, Math.ceil(data.count / PAGE_SIZE));
  const heading = params.search ? `Results for “${params.search}”` : current ? current.name : "All products";

  return (
    <div className="grid gap-10 md:grid-cols-[220px_1fr]">
      <aside aria-label="Filters" className="space-y-8">
        <nav aria-label="Categories">
          <h2 className="mb-3 text-lg font-bold">Categories</h2>
          <ul className="space-y-1.5">
            <li>
              <Link href={linkWith(params, { category: "" })} className={!params.category ? "font-semibold text-cobalt" : "hover:text-cobalt"}>
                Everything
              </Link>
            </li>
            {tree.map((parent) => (
              <li key={parent.slug}>
                <Link
                  href={linkWith(params, { category: parent.slug })}
                  className={params.category === parent.slug ? "font-semibold text-cobalt" : "hover:text-cobalt"}
                >
                  {parent.name}
                </Link>
                <ul className="ml-3 mt-1 space-y-1 border-l border-line pl-3 text-sm">
                  {parent.children.map((child) => (
                    <li key={child.slug}>
                      <Link
                        href={linkWith(params, { category: child.slug })}
                        className={params.category === child.slug ? "font-semibold text-cobalt" : "text-ink-soft hover:text-cobalt"}
                      >
                        {child.name}
                      </Link>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </nav>

        {/* A plain GET form: filtering works even before JavaScript loads. */}
        <form action="/products" className="space-y-4">
          <h2 className="text-lg font-bold">Refine</h2>
          {["category", "search", "ordering"].map((key) =>
            params[key] ? <input key={key} type="hidden" name={key} value={params[key]} /> : null,
          )}
          <fieldset>
            <legend className="mb-1 text-sm font-medium">Price (£)</legend>
            <div className="flex items-center gap-2">
              <input name="min_price" type="number" min="0" step="1" defaultValue={params.min_price} placeholder="Min"
                aria-label="Minimum price" className="w-full rounded-sm border border-line bg-white px-2 py-1.5" />
              <span aria-hidden="true">to</span>
              <input name="max_price" type="number" min="0" step="1" defaultValue={params.max_price} placeholder="Max"
                aria-label="Maximum price" className="w-full rounded-sm border border-line bg-white px-2 py-1.5" />
            </div>
          </fieldset>
          {[
            ["brand", "Brand", "e.g. Nova, Stride"],
            ["colour", "Colour", "e.g. Black"],
            ["size", "Size", "e.g. M, 9, 128GB"],
          ].map(([name, label, placeholder]) => (
            <label key={name} className="block">
              <span className="mb-1 block text-sm font-medium">{label}</span>
              <input name={name} defaultValue={params[name]} placeholder={placeholder}
                className="w-full rounded-sm border border-line bg-white px-2 py-1.5" />
            </label>
          ))}
          <div className="flex items-center gap-4">
            <button className="rounded-sm bg-ink px-4 py-2 font-semibold text-white hover:bg-cobalt">Apply</button>
            <Link href={linkWith({ category: params.category, search: params.search }, {})} className="text-sm text-cobalt hover:underline">
              Clear
            </Link>
          </div>
        </form>
      </aside>

      <section aria-labelledby="results-heading">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-4 border-b border-line pb-4">
          <div>
            <h1 id="results-heading" className="text-4xl font-extrabold">{heading}</h1>
            <p className="mt-1 text-ink-soft" aria-live="polite">
              {data.count} {data.count === 1 ? "product" : "products"}
            </p>
          </div>
          <SortSelect value={params.ordering || "-created_at"} />
        </div>

        {data.results.length ? (
          <div className="grid grid-cols-2 gap-x-5 gap-y-8 lg:grid-cols-3">
            {data.results.map((product) => (
              <ProductTile key={product.id} product={product} />
            ))}
          </div>
        ) : (
          <div className="py-16">
            <h2 className="text-2xl font-bold">Nothing matches those filters</h2>
            <p className="mt-2 text-ink-soft">Try a wider price range, another colour, or fewer words in the search.</p>
            <Link href="/products" className="mt-4 inline-block font-medium text-cobalt hover:underline">Show all products</Link>
          </div>
        )}

        {pages > 1 && (
          <nav aria-label="Pages" className="mt-12 flex items-center gap-4">
            {page > 1 && <Link href={linkWith(params, { page: page - 1 })} className="font-medium text-cobalt hover:underline">Previous</Link>}
            <span className="text-ink-soft">Page {page} of {pages}</span>
            {page < pages && <Link href={linkWith(params, { page: page + 1 })} className="font-medium text-cobalt hover:underline">Next</Link>}
          </nav>
        )}
      </section>
    </div>
  );
}
