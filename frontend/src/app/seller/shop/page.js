"use client";

import { useEffect, useState } from "react";

import PanelShell, { PageTitle } from "@/components/panel/PanelShell";
import { Button, Field, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { shopStatusLabel, shopStatusNote } from "@/lib/seller";

const PILL = {
  pending: "text-ink-soft shadow-[inset_0_0_0_2px_var(--line)]",
  approved: "text-accent shadow-[inset_0_0_0_2px_var(--accent)]",
  suspended: "text-power shadow-[inset_0_0_0_2px_var(--power)]",
};

function Shop() {
  const [shop, setShop] = useState(null);
  const [form, setForm] = useState({ shop_name: "", description: "" });
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState({});
  const [saved, setSaved] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api("/api/v1/sellers/me/")
      .then((data) => {
        setShop(data);
        setForm({ shop_name: data.shop_name, description: data.description });
      })
      .catch((err) => setError(err.message));
  }, []);

  async function save(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setSaved("");
    setFieldErrors({});
    try {
      const data = await api("/api/v1/sellers/me/", { method: "PATCH", body: form });
      setShop(data);
      setSaved("Shop saved.");
    } catch (err) {
      if (err.status === 400 && err.data && typeof err.data === "object") {
        setFieldErrors(
          Object.fromEntries(
            Object.entries(err.data).map(([key, value]) => [key, Array.isArray(value) ? value.join(" ") : String(value)]),
          ),
        );
      } else {
        setError(err.message);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <PanelShell role="seller">
      <PageTitle title="My shop" lede="Shoppers see this name and description next to your products." />

      <div className="mb-4 space-y-3">
        <Notice tone="error">{error}</Notice>
        <Notice tone="success">{saved}</Notice>
      </div>

      {shop === null && !error && <p className="text-ink-soft">Loading your shop…</p>}

      {shop && (
        <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
          <form onSubmit={save} className="raised space-y-5 p-7" noValidate>
            <Field
              label="Shop name"
              name="shop_name"
              required
              maxLength={120}
              value={form.shop_name}
              onChange={(e) => setForm({ ...form, shop_name: e.target.value })}
              error={fieldErrors.shop_name}
            />
            <div>
              <label htmlFor="shop-description" className="mb-1.5 block text-sm font-medium">Description</label>
              <textarea
                id="shop-description"
                name="description"
                rows={4}
                maxLength={1000}
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                aria-invalid={fieldErrors.description ? true : undefined}
                aria-describedby={fieldErrors.description ? "shop-description-error" : "shop-description-hint"}
                className="field resize-y"
              />
              {fieldErrors.description ? (
                <span id="shop-description-error" className="mt-1.5 block text-sm font-medium text-power">{fieldErrors.description}</span>
              ) : (
                <span id="shop-description-hint" className="mt-1.5 block text-sm text-ink-soft">Up to 1,000 characters.</span>
              )}
            </div>
            <Button type="submit" busy={busy}>{busy ? "Saving…" : "Save shop"}</Button>
          </form>

          <section aria-labelledby="shop-status-heading" className="raised h-fit p-6">
            <h2 id="shop-status-heading" className="text-xl font-extrabold">Shop status</h2>
            <p className="mt-4">
              <span className={`inline-block rounded-full px-3 py-0.5 text-sm font-semibold ${PILL[shop.status] || ""}`}>
                {shopStatusLabel(shop.status)}
              </span>
            </p>
            <p className="mt-4 text-sm leading-relaxed text-ink-soft">{shopStatusNote(shop.status)}</p>
            <p className="mt-3 text-sm leading-relaxed text-ink-soft">Only an admin can change this status.</p>
          </section>
        </div>
      )}
    </PanelShell>
  );
}

export default function SellerShopPage() {
  return <Shop />;
}
