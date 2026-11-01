import Link from "next/link";

import CatalogueUnavailable from "@/components/CatalogueUnavailable";
import ProductTile from "@/components/ProductTile";
import SortSelect from "@/components/SortSelect";
import { CatalogueDown, findCategory, getCategoryTree, getProducts } from "@/lib/catalog-server";

const FILTER_KEYS = ["category", "search", "brand", "min_price", "max_price", "colour", "size", "on_sale", "ordering", "page"];
const PAGE_SIZE = 12;

export async function generateMetadata({ searchParams }) {
  const { search, on_sale } = await searchParams;
  return { title: search ? `Results for “${search}”` : on_sale ? "On sale" : "All products" };
}

function linkWith(params, changes) {
  const next = { ...params, ...changes };
  if (!("page" in changes)) delete next.page; // a new filter starts again from page 1
  const query = new URLSearchParams(Object.entries(next).filter(([, v]) => v));
  return `/products${query.toString() ? `?${query}` : ""}`;
}

function CategoryLink({ params, slug, children, small = false }) {
  const active = (params.category || "") === slug;
  return (
    <Link
      href={linkWith(params, { category: slug })}
      aria-current={active ? "page" : undefined}
      className={`flex items-center gap-2 ${small ? "text-sm" : ""} ${active ? "font-semibold text-accent" : small ? "text-ink-soft hover:text-accent" : "hover:text-accent"}`}
    >
      {/* the active category gets a small red marker */}
      <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${active ? "bg-power shadow-[var(--power-glow)]" : "bg-transparent"}`} />
      {children}
    </Link>
  );
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
  const heading = params.search
    ? `Results for “${params.search}”`
    : current ? current.name : params.on_sale ? "On sale" : "All products";

  return (
    <div className="grid gap-10 md:grid-cols-[240px_1fr]">
      <aside aria-label="Filters" className="space-y-8">
        <nav aria-label="Categories" className="raised p-5">
          <h2 className="mb-3 text-lg font-bold">Categories</h2>
          <ul className="space-y-2">
            <li><CategoryLink params={params} slug="">Everything</CategoryLink></li>
            {tree.map((parent) => (
              <li key={parent.slug}>
                <CategoryLink params={params} slug={parent.slug}>{parent.name}</CategoryLink>
                <ul className="ml-3.5 mt-1.5 space-y-1.5">
                  {parent.children.map((child) => (
                    <li key={child.slug}>
                      <CategoryLink params={params} slug={child.slug} small>{child.name}</CategoryLink>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </nav>

        {/* A plain GET form: filtering works even before JavaScript loads. */}
        <form action="/products" className="raised space-y-4 p-5">
          <h2 className="text-lg font-bold">Refine</h2>
          {["category", "search", "ordering"].map((key) =>
            params[key] ? <input key={key} type="hidden" name={key} value={params[key]} /> : null,
          )}
          <fieldset>
            <legend className="mb-1.5 text-sm font-medium">Price (£)</legend>
            <div className="flex items-center gap-2">
              <input name="min_price" type="number" min="0" step="1" defaultValue={params.min_price} placeholder="Min"
                aria-label="Minimum price" className="field px-3 py-2" />
              <span aria-hidden="true" className="text-ink-soft">to</span>
              <input name="max_price" type="number" min="0" step="1" defaultValue={params.max_price} placeholder="Max"
                aria-label="Maximum price" className="field px-3 py-2" />
            </div>
          </fieldset>
          {[
            ["brand", "Brand", "e.g. Nova, Stride"],
            ["colour", "Colour", "e.g. Black"],
            ["size", "Size", "e.g. M, 9, 128GB"],
          ].map(([name, label, placeholder]) => (
            <label key={name} className="block">
              <span className="mb-1.5 block text-sm font-medium">{label}</span>
              <input name={name} defaultValue={params[name]} placeholder={placeholder} className="field px-3 py-2" />
            </label>
          ))}
          <label className="flex items-center gap-3 text-sm font-medium">
            <input type="checkbox" name="on_sale" value="true" defaultChecked={params.on_sale === "true"} className="h-4 w-4 accent-[var(--power)]" />
            On sale only
          </label>
          <div className="flex items-center gap-4 pt-1">
            <button className="btn btn-metal px-5 py-2.5">Apply</button>
            <Link href={linkWith({ category: params.category, search: params.search }, {})} className="text-sm font-medium text-accent hover:underline">
              Clear
            </Link>
          </div>
        </form>
      </aside>

      <section aria-labelledby="results-heading">
        <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 id="results-heading" className="text-4xl font-extrabold sm:text-5xl">{heading}</h1>
            <p className="mt-2 text-ink-soft" aria-live="polite">
              {data.count} {data.count === 1 ? "product" : "products"}
            </p>
          </div>
          <SortSelect value={params.ordering || "-created_at"} />
        </div>

        {data.results.length ? (
          <div className="grid grid-cols-2 gap-5 sm:gap-7 lg:grid-cols-3">
            {data.results.map((product) => (
              <ProductTile key={product.id} product={product} />
            ))}
          </div>
        ) : (
          <div className="raised px-8 py-14">
            <h2 className="text-2xl font-bold">Nothing matches those filters</h2>
            <p className="mt-2 text-ink-soft">Try a wider price range, another colour, or fewer words in the search.</p>
            <Link href="/products" className="btn btn-metal mt-6">Show all products</Link>
          </div>
        )}

        {pages > 1 && (
          <nav aria-label="Pages" className="mt-12 flex items-center gap-4">
            {page > 1 && <Link href={linkWith(params, { page: page - 1 })} className="btn btn-soft">Previous</Link>}
            <span className="text-ink-soft">Page {page} of {pages}</span>
            {page < pages && <Link href={linkWith(params, { page: page + 1 })} className="btn btn-soft">Next</Link>}
          </nav>
        )}
      </section>
    </div>
  );
}
