"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import PanelShell, { PageTitle } from "@/components/panel/PanelShell";
import { Button, Field, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { saleRequest } from "@/lib/flashSale";

let nextKey = 1;

function blankItem() {
  return { key: nextKey++, slug: "", product: null, variant: "", sale_price: "", quantity_cap: "", loadError: "" };
}

function variantLabel(variant) {
  return [variant.sku, variant.colour, variant.size].filter(Boolean).join(" · ");
}

function NewFlashSale() {
  const router = useRouter();
  const [form, setForm] = useState({ name: "", starts_at: "", ends_at: "" });
  const [items, setItems] = useState([blankItem()]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState({});

  const update = (key) => (event) => setForm((current) => ({ ...current, [key]: event.target.value }));
  const changeItem = (key, patch) =>
    setItems((current) => current.map((item) => (item.key === key ? { ...item, ...patch } : item)));

  async function loadProduct(key) {
    const item = items.find((candidate) => candidate.key === key);
    const slug = item.slug.trim();
    if (!slug) return;
    try {
      const product = await api(`/api/v1/products/${encodeURIComponent(slug)}/`);
      changeItem(key, { product, variant: "", loadError: "" });
    } catch (err) {
      changeItem(key, { product: null, variant: "", loadError: `No product called “${slug}”.` });
    }
  }

  async function create(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setFieldErrors({});
    try {
      await api("/api/v1/admin/flash-sales/", { method: "POST", body: saleRequest({ ...form, items }) });
      router.push("/admin/flash-sales");
    } catch (err) {
      if (err.status === 400 && err.data && typeof err.data === "object") {
        const { non_field_errors: general, ...fields } = err.data;
        setFieldErrors(Object.fromEntries(Object.entries(fields).map(([key, value]) => [key, [].concat(value).join(" ")])));
        if (general) setError([].concat(general).join(" "));
        else if (!Object.keys(fields).length) setError(err.message);
      } else {
        setError(err.message);
      }
      setBusy(false);
    }
  }

  return (
    <PanelShell role="admin">
      <PageTitle
        title="New flash sale"
        lede="Pick the items, set a sale price below each regular price and say how many units each item can sell. Times are London time."
      />

      {error && <div className="mb-4"><Notice>{error}</Notice></div>}

      <form onSubmit={create} noValidate className="raised max-w-3xl space-y-7 p-7">
        <Field label="Name" maxLength={120} required value={form.name} onChange={update("name")}
          name="name" error={fieldErrors.name} />

        <div className="grid gap-5 sm:grid-cols-2">
          <Field label="Starts" type="datetime-local" required value={form.starts_at} onChange={update("starts_at")}
            name="starts_at" error={fieldErrors.starts_at} />
          <Field label="Ends" type="datetime-local" required value={form.ends_at} onChange={update("ends_at")}
            name="ends_at" error={fieldErrors.ends_at} />
        </div>

        <fieldset className="space-y-5">
          <legend className="mb-1 font-display text-xl font-bold">Items</legend>

          {items.map((item, index) => (
            <div key={item.key} className="inset space-y-4 rounded-2xl p-5">
              <div className="flex flex-wrap items-end gap-3">
                <label className="min-w-0 flex-1" htmlFor={`slug-${item.key}`}>
                  <span className="mb-1.5 block text-sm font-medium">Product slug</span>
                  <input id={`slug-${item.key}`} className="field" value={item.slug}
                    onChange={(event) => changeItem(item.key, { slug: event.target.value })} />
                </label>
                <Button variant="secondary" type="button" onClick={() => loadProduct(item.key)}>Find product</Button>
                {items.length > 1 && (
                  <Button variant="quiet" type="button" onClick={() => setItems((current) => current.filter((c) => c.key !== item.key))}>
                    Remove item {index + 1}
                  </Button>
                )}
              </div>
              {item.loadError && <p role="alert" className="text-sm font-semibold text-power">{item.loadError}</p>}
              {item.product && (
                <p className="text-sm text-ink-soft">{item.product.name}</p>
              )}

              {item.product && (
                <div className="grid gap-4 sm:grid-cols-2">
                  <label className="block" htmlFor={`variant-${item.key}`}>
                    <span className="mb-1.5 block text-sm font-medium">Variant</span>
                    <select id={`variant-${item.key}`} className="field" value={item.variant}
                      onChange={(event) => changeItem(item.key, { variant: event.target.value })}>
                      <option value="">Choose a variant</option>
                      {item.product.variants.map((variant) => (
                        <option key={variant.id} value={variant.id}>
                          {variantLabel(variant)} · £{variant.price}
                        </option>
                      ))}
                    </select>
                  </label>
                  <Field label="Sale price (£)" inputMode="decimal" value={item.sale_price}
                    onChange={(event) => changeItem(item.key, { sale_price: event.target.value })}
                    name={`sale-${item.key}`} hint="Must be below the regular price." />
                  <Field label="Cap (units)" type="number" min={1} value={item.quantity_cap}
                    onChange={(event) => changeItem(item.key, { quantity_cap: event.target.value })}
                    name={`cap-${item.key}`} hint="Leave empty for no cap." />
                </div>
              )}
            </div>
          ))}

          <Button variant="secondary" type="button"
            onClick={() => setItems((current) => [...current, blankItem()])}>Add item</Button>
        </fieldset>

        <div className="flex justify-end gap-3">
          <Link href="/admin/flash-sales" className="btn btn-soft">Cancel</Link>
          <Button type="submit" busy={busy}>{busy ? "Creating…" : "Create flash sale"}</Button>
        </div>
      </form>
    </PanelShell>
  );
}

export default function NewFlashSalePage() {
  return <NewFlashSale />;
}
