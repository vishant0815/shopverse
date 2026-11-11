"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Button, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { money } from "@/lib/format";

import { ProductStatus } from "./PanelShell";

const TABS = [
  ["", "All"],
  ["active", "Published"],
  ["draft", "Drafts"],
  ["archived", "Archived"],
];

// Used by both panels: sellers get their own products, admins get everyone's
// (the products service decides which, from the role in the token).
export default function ProductList({ editBase, showSeller = false }) {
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(null);

  const load = useCallback(async () => {
    const params = new URLSearchParams({ page: String(page), page_size: "20" });
    if (status) params.set("status", status);
    if (query) params.set("search", query);
    try {
      setData(await api(`/api/v1/seller/products/?${params}`));
      setError("");
    } catch (err) {
      setError(err.status === 404 ? "" : err.message);
      if (err.status === 404) setPage(1);
    }
  }, [status, query, page]);

  useEffect(() => {
    load();
  }, [load]);

  async function archive(product) {
    if (!window.confirm(`Archive “${product.name}”? It disappears from the shop, but past orders keep it.`)) return;
    setBusy(product.id);
    try {
      await api(`/api/v1/seller/products/${product.id}/`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap gap-3" role="group" aria-label="Filter by status">
          {TABS.map(([value, label]) => (
            <button
              key={value || "all"}
              aria-pressed={status === value}
              onClick={() => { setStatus(value); setPage(1); }}
              className={`raised-sm px-4 py-2 font-semibold ${status === value ? "pressed" : "hover:text-accent"}`}
            >
              {label}
            </button>
          ))}
        </div>
        <form
          role="search"
          onSubmit={(e) => { e.preventDefault(); setQuery(search.trim()); setPage(1); }}
          className="inset flex items-center gap-2 py-1 pl-3 pr-1"
        >
          <label htmlFor="product-search" className="sr-only">Search products</label>
          <input id="product-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search by name or brand"
            className="w-48 bg-transparent py-1.5 outline-none placeholder:text-ink-soft" />
          <button className="btn btn-soft px-3 py-1.5 text-sm">Search</button>
        </form>
      </div>

      <Notice>{error}</Notice>

      <section className="raised p-4 sm:p-5">
        {!data ? (
          <p className="p-2 text-ink-soft">Loading products…</p>
        ) : data.results.length === 0 ? (
          <p className="p-2 text-ink-soft">No products here.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead className="text-sm text-ink-soft">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium">Product</th>
                  {showSeller && <th scope="col" className="px-3 py-2 font-medium">Seller</th>}
                  <th scope="col" className="px-3 py-2 font-medium">Status</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">From</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {data.results.map((product) => (
                  <tr key={product.id} className="border-t border-line">
                    <td className="px-3 py-3">
                      <div className="flex items-center gap-3">
                        <div className="inset h-12 w-12 shrink-0 overflow-hidden rounded-lg">
                          {product.thumbnail && (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img src={product.thumbnail} alt="" className="photo h-full w-full object-cover" />
                          )}
                        </div>
                        <div>
                          <Link href={`${editBase}/${product.id}`} className="font-semibold hover:text-accent">{product.name}</Link>
                          <span className="block text-sm text-ink-soft">{product.brand || "No brand"} · {product.category.name}</span>
                        </div>
                      </div>
                    </td>
                    {showSeller && <td className="px-3 py-3 font-mono text-xs text-ink-soft">{product.seller_id.slice(0, 8)}</td>}
                    <td className="px-3 py-3"><ProductStatus status={product.status} /></td>
                    <td className="whitespace-nowrap px-3 py-3 text-right font-display font-extrabold">
                      {product.min_price ? <span className="metal-text">{money(product.min_price)}</span> : <span className="text-ink-soft">No options</span>}
                    </td>
                    <td className="whitespace-nowrap px-3 py-3 text-right">
                      <Link href={`${editBase}/${product.id}`} className="btn btn-soft px-3 py-1.5 text-sm">Edit</Link>
                      {product.status !== "archived" && (
                        <button onClick={() => archive(product)} disabled={busy === product.id}
                          className="ml-3 text-sm font-semibold text-power hover:underline disabled:opacity-50">
                          Archive
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {data && (data.next || data.previous) && (
        <div className="mt-6 flex items-center gap-4">
          <Button variant="secondary" disabled={!data.previous} onClick={() => setPage((p) => p - 1)}>Previous</Button>
          <span className="text-ink-soft">Page {page} of {Math.ceil(data.count / 20)}</span>
          <Button variant="secondary" disabled={!data.next} onClick={() => setPage((p) => p + 1)}>Next</Button>
        </div>
      )}
    </>
  );
}
