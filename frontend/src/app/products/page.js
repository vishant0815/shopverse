import Link from "next/link";

import CatalogueUnavailable from "@/components/CatalogueUnavailable";
import ProductTile from "@/components/ProductTile";
import SortSelect from "@/components/SortSelect";
import { CatalogueDown, findCategory, getCategoryTree, getProducts, SearchDown, searchProducts } from "@/lib/catalog-server";
import { money } from "@/lib/format";
import { buildHref, PAGE_SIZE, parseSearchParams, toProductsQuery, toSearchQuery } from "@/lib/search-model";

const COLOUR_CHIPS = 8; // the rest of the colours sit behind "Show more"

export async function generateMetadata({ searchParams }) {
  const params = parseSearchParams(await searchParams);
  return { title: params.search ? `Results for “${params.search}”` : params.on_sale ? "On sale" : "All products" };
}

// Search provides the listing and its facets. On-sale browsing still comes from the products service,
// because the search index doesn't store discounts yet. If search is down, the products service stands in
// without facets, so the shop keeps working.
async function loadListing(params) {
  if (params.on_sale) {
    return { data: await getProducts(toProductsQuery(params)), facets: null, searchDown: false };
  }
  try {
    const data = await searchProducts(toSearchQuery(params));
    return { data, facets: data.facets, searchDown: false };
  } catch (error) {
    if (!(error instanceof SearchDown)) throw error;
    return { data: await getProducts(toProductsQuery(params)), facets: null, searchDown: true };
  }
}

function CategoryLink({ params, slug, children, small = false }) {
  const active = (params.category || "") === slug;
  return (
    <Link
      href={buildHref(params, { category: slug })}
      aria-current={active ? "page" : undefined}
      className={`flex items-center gap-2 ${small ? "text-sm" : ""} ${active ? "font-semibold text-accent" : small ? "text-ink-soft hover:text-accent" : "hover:text-accent"}`}
    >
      {/* the active category gets a small red marker */}
      <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${active ? "bg-power shadow-[var(--power-glow)]" : "bg-transparent"}`} />
      {children}
    </Link>
  );
}

function FacetChip({ params, name, option }) {
  const active = params[name] === option.value;
  return (
    <li>
      <Link
        href={buildHref(params, { [name]: active ? "" : option.value })}
        aria-current={active ? "true" : undefined}
        className={`inset flex items-center gap-2 px-3 py-1.5 text-sm ${active ? "font-semibold text-accent" : ""}`}
      >
        {option.value} <span className="text-ink-soft">{option.count}</span>
      </Link>
    </li>
  );
}

function FacetGroup({ params, name, title, options, limit }) {
  const shown = limit ? options.slice(0, limit) : options;
  const hidden = limit ? options.slice(limit) : [];
  return (
    <div>
      <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-soft">{title}</h3>
      <ul className="flex flex-wrap gap-2">
        {shown.map((option) => <FacetChip key={option.value} params={params} name={name} option={option} />)}
      </ul>
      {hidden.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer text-sm font-medium text-accent">Show {hidden.length} more</summary>
          <ul className="mt-2 flex flex-wrap gap-2">
            {hidden.map((option) => <FacetChip key={option.value} params={params} name={name} option={option} />)}
          </ul>
        </details>
      )}
    </div>
  );
}

export default async function ProductsPage({ searchParams }) {
  const params = parseSearchParams(await searchParams);

  let tree, listing;
  try {
    [tree, listing] = await Promise.all([getCategoryTree(), loadListing(params)]);
  } catch (error) {
    if (error instanceof CatalogueDown) return <CatalogueUnavailable />;
    throw error;
  }
  // An out-of-range page comes back as 404 from the products service.
  const { data, facets, searchDown } = listing;
  const results = data?.results ?? [];
  const count = data?.count ?? 0;
  const pages = Math.max(1, Math.ceil(count / PAGE_SIZE));

  const current = params.category ? findCategory(tree, params.category) : null;
  const heading = params.search
    ? `Results for “${params.search}”`
    : current ? current.name : params.on_sale ? "On sale" : "All products";
  const price = facets?.price;

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

        {facets && (
          <div className="raised space-y-6 p-5">
            <h2 className="text-lg font-bold">Refine results</h2>
            {facets.colours.length > 0 && (
              <FacetGroup params={params} name="colour" title="Colour" options={facets.colours} limit={COLOUR_CHIPS} />
            )}
            {facets.sizes.length > 0 && (
              <FacetGroup params={params} name="size" title="Size" options={facets.sizes} />
            )}
          </div>
        )}

        {/* A plain GET form: filtering works even before JavaScript loads. */}
        <form action="/products" className="raised space-y-4 p-5">
          <h2 className="text-lg font-bold">Refine</h2>
          {["search", "category", "sort", "on_sale"].map((key) =>
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
            {price?.min && price?.max && (
              <p className="mt-2 text-sm text-ink-soft">In these results: {money(price.min)} to {money(price.max)}</p>
            )}
          </fieldset>
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium">Brand</span>
            <input name="brand" defaultValue={params.brand} placeholder="e.g. Nova, Stride" className="field px-3 py-2" />
          </label>
          <label className="flex items-center gap-3 text-sm font-medium">
            <input type="checkbox" name="on_sale" value="true" defaultChecked={params.on_sale === "true"} className="h-4 w-4 accent-[var(--power)]" />
            On sale only
          </label>
          <div className="flex items-center gap-4 pt-1">
            <button className="btn btn-metal px-5 py-2.5">Apply</button>
            <Link href={buildHref({ category: params.category, search: params.search }, {})} className="text-sm font-medium text-accent hover:underline">
              Clear
            </Link>
          </div>
        </form>
      </aside>

      <section aria-labelledby="results-heading">
        {searchDown && (
          <div role="status" className="raised mb-8 p-6">
            <h2 className="text-lg font-bold">Search is temporarily unavailable</h2>
            <p className="mt-1 text-ink-soft">Colour and size filters are hidden for now. Try again in a moment.</p>
          </div>
        )}

        <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 id="results-heading" className="text-4xl font-extrabold sm:text-5xl">{heading}</h1>
            <p className="mt-2 text-ink-soft" aria-live="polite">
              {count} {count === 1 ? "product" : "products"}
            </p>
          </div>
          <SortSelect value={params.sort} />
        </div>

        {results.length ? (
          <div className="grid grid-cols-2 gap-5 sm:gap-7 lg:grid-cols-3">
            {results.map((product) => (
              <ProductTile key={product.id} product={product} />
            ))}
          </div>
        ) : (
          <div className="raised px-8 py-14">
            <h2 className="text-2xl font-bold">
              {params.search ? "Check the spelling, or try a broader word" : "Nothing matches those filters"}
            </h2>
            <p className="mt-2 text-ink-soft">Try fewer words, check the spelling, or widen the filters.</p>
            <Link href="/products" className="btn btn-metal mt-6">Show all products</Link>
          </div>
        )}

        {pages > 1 && (
          <nav aria-label="Pages" className="mt-12 flex items-center gap-4">
            {params.page > 1 && <Link href={buildHref(params, { page: params.page - 1 })} className="btn btn-soft">Previous</Link>}
            <span className="text-ink-soft">Page {params.page} of {pages}</span>
            {params.page < pages && <Link href={buildHref(params, { page: params.page + 1 })} className="btn btn-soft">Next</Link>}
          </nav>
        )}
      </section>
    </div>
  );
}
