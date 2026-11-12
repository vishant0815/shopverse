"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { Button, Field, Notice } from "@/components/ui";
import { api } from "@/lib/api";

const STATUSES = [
  ["draft", "Draft"],
  ["active", "Published"],
  ["archived", "Archived"],
];

const blankVariant = () => ({ key: crypto.randomUUID(), sku: "", colour: "", size: "", price: "", compare_at_price: "", on_hand: "", reserved: 0 });
const blankImage = () => ({ key: crypto.randomUUID(), url: "", alt_text: "" });

// Categories come back flat, with each child naming its parent; show them as "Fashion › Footwear".
function categoryOptions(categories) {
  const bySlug = Object.fromEntries(categories.map((c) => [c.slug, c]));
  return categories
    .map((c) => ({ slug: c.slug, label: c.parent && bySlug[c.parent] ? `${bySlug[c.parent].name} › ${c.name}` : c.name }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

function variantPayload(v) {
  return {
    sku: v.sku.trim(),
    colour: v.colour.trim(),
    size: v.size.trim(),
    price: v.price,
    compare_at_price: v.compare_at_price === "" ? null : v.compare_at_price,
  };
}

function changed(original, current) {
  const a = variantPayload({ ...original, compare_at_price: original.compare_at_price ?? "" });
  const b = variantPayload(current);
  return Object.keys(a).some((key) => String(a[key] ?? "") !== String(b[key] ?? ""));
}

// Stock levels for these variants: { [variantId]: { on_hand, reserved } }. Inventory being down
// shouldn't stop the seller saving options and photos, so this answers {} rather than failing.
async function loadStock(ids) {
  if (!ids.length) return {};
  try {
    const { results } = await api(`/api/v1/inventory/stock?variant_ids=${ids.join(",")}`);
    return Object.fromEntries(results.map((row) => [row.variant_id, row]));
  } catch {
    return {};
  }
}

function withStock(rows, stock) {
  return rows.map((v) => ({
    ...v,
    on_hand: stock[v.id] ? String(stock[v.id].on_hand) : "",
    reserved: stock[v.id]?.reserved ?? 0,
  }));
}

// A brand-new option reaches inventory a moment after it's saved (catalogue events), so
// the service answers "not_ready" until then. Keep asking for a few seconds.
async function setStock(variantId, onHand) {
  for (let attempt = 1; ; attempt += 1) {
    try {
      return await api(`/api/v1/inventory/stock/${variantId}`, { method: "PUT", body: { on_hand: onHand } });
    } catch (err) {
      if (err.status === 404 && err.data?.code === "not_ready" && attempt < 10) {
        await new Promise((resolve) => setTimeout(resolve, 500));
        continue;
      }
      throw err;
    }
  }
}

// Saves the "In stock" numbers that changed. Returns the options that couldn't be saved.
async function syncStock(targets, baseline) {
  const failed = [];
  for (const { id, row } of targets) {
    const value = row.on_hand.trim();
    if (value === "" || value === baseline(id)) continue;
    try {
      await setStock(id, Number(value));
    } catch (err) {
      failed.push(`${row.sku.trim() || "an option"} (${describe(err)})`);
    }
  }
  return failed;
}

// The API reports errors as {field: [messages]}, sometimes nested; flatten to one sentence.
function describe(err) {
  if (!err.data || typeof err.data !== "object") return err.message;
  const parts = [];
  const walk = (value, label) => {
    if (Array.isArray(value)) value.forEach((v) => (typeof v === "string" ? parts.push(label ? `${label}: ${v}` : v) : walk(v, label)));
    else if (value && typeof value === "object") Object.entries(value).forEach(([k, v]) => walk(v, k === "detail" || k === "non_field_errors" ? label : k.replaceAll("_", " ")));
    else if (typeof value === "string") parts.push(label ? `${label}: ${value}` : value);
  };
  walk(err.data, "");
  return parts.join(" ") || err.message;
}

export default function ProductEditor({ productId, listHref }) {
  const router = useRouter();
  const isNew = !productId;
  const [categories, setCategories] = useState([]);
  const [form, setForm] = useState({ name: "", brand: "", description: "", category: "", status: "draft" });
  const [variants, setVariants] = useState([blankVariant()]);
  const [original, setOriginal] = useState({ variants: [], images: [] });
  const [images, setImages] = useState([]);
  const [loaded, setLoaded] = useState(isNew);
  const [state, setState] = useState({ busy: false, error: "", saved: false });

  useEffect(() => {
    (async () => {
      try {
        const cats = await api("/api/v1/categories/");
        setCategories(cats);
        if (isNew) {
          setForm((f) => ({ ...f, category: f.category || "" }));
          return;
        }
        const product = await api(`/api/v1/seller/products/${productId}/`);
        setForm({
          name: product.name,
          brand: product.brand,
          description: product.description,
          category: product.category.slug,
          status: product.status,
        });
        const active = product.variants
          .filter((v) => v.is_active)
          .map((v) => ({ ...v, key: v.id, price: String(v.price), compare_at_price: v.compare_at_price ? String(v.compare_at_price) : "" }));
        const rows = withStock(active, await loadStock(active.map((v) => v.id)));
        setVariants(rows.length ? rows : [blankVariant()]);
        setImages(product.images.map((i) => ({ ...i, key: String(i.id) })));
        setOriginal({ variants: rows, images: product.images });
        if (new URLSearchParams(window.location.search).get("stock") === "later") {
          setState((s) => ({ ...s, error: "Some stock numbers weren't saved when the product was created. Check the “In stock” column and save again." }));
        }
        setLoaded(true);
      } catch (err) {
        setState((s) => ({ ...s, error: err.status === 404 ? "This product doesn't exist, or it isn't yours." : err.message }));
      }
    })();
  }, [isNew, productId]);

  const options = useMemo(() => categoryOptions(categories), [categories]);
  const set = (key) => (e) => { setForm({ ...form, [key]: e.target.value }); setState((s) => ({ ...s, saved: false })); };
  const setVariant = (key, field, value) => setVariants((list) => list.map((v) => (v.key === key ? { ...v, [field]: value } : v)));
  const setImage = (key, field, value) => setImages((list) => list.map((i) => (i.key === key ? { ...i, [field]: value } : i)));

  function checkForm() {
    if (!form.name.trim()) return "Give the product a name.";
    if (!form.category) return "Choose a category.";
    const filled = variants.filter((v) => v.sku || v.price || v.colour || v.size);
    for (const [index, v] of filled.entries()) {
      if (!v.sku.trim()) return `Option ${index + 1}: add an item code.`;
      if (!(Number(v.price) > 0)) return `Option ${index + 1}: the price must be more than £0.`;
      if (v.compare_at_price !== "" && Number(v.compare_at_price) < Number(v.price)) {
        return `Option ${index + 1}: the “was” price can't be lower than the price.`;
      }
      if (v.on_hand.trim() !== "" && !/^\d+$/.test(v.on_hand.trim())) {
        return `Option ${index + 1}: in stock must be a whole number.`;
      }
    }
    if (form.status === "active" && filled.length === 0) return "Add at least one option with a price before publishing.";
    return "";
  }

  async function save(event) {
    event.preventDefault();
    const problem = checkForm();
    if (problem) {
      setState({ busy: false, error: problem, saved: false });
      return;
    }
    setState({ busy: true, error: "", saved: false });
    const filledVariants = variants.filter((v) => v.sku || v.price || v.colour || v.size);
    const filledImages = images.filter((i) => i.url.trim());
    const core = { name: form.name.trim(), brand: form.brand.trim(), description: form.description.trim(), category: form.category };

    try {
      if (isNew) {
        const created = await api("/api/v1/seller/products/", {
          method: "POST",
          body: {
            ...core,
            status: form.status,
            variants: filledVariants.map(variantPayload),
            images: filledImages.map((i, position) => ({ url: i.url.trim(), alt_text: i.alt_text.trim(), position })),
          },
        });
        const targets = filledVariants.map((row) => ({ row, id: created.variants?.find((c) => c.sku === row.sku.trim())?.id }));
        const failed = await syncStock(targets.filter((t) => t.id), () => "");
        const missed = targets.some((t) => !t.id && t.row.on_hand.trim() !== "");
        router.replace(`${listHref}/${created.id}?created=1${failed.length || missed ? "&stock=later" : ""}`);
        return;
      }

      // Existing product: sync options and photos first, so a "Published" status is only
      // sent once the product really has an active option.
      const base = `/api/v1/seller/products/${productId}`;
      const keptIds = new Set(filledVariants.filter((v) => v.id).map((v) => v.id));
      for (const old of original.variants) {
        if (!keptIds.has(old.id)) await api(`${base}/variants/${old.id}/`, { method: "DELETE" });
      }
      const stockTargets = [];
      for (const v of filledVariants) {
        if (!v.id) {
          const created = await api(`${base}/variants/`, { method: "POST", body: variantPayload(v) });
          stockTargets.push({ id: created.id, row: v });
        } else {
          const before = original.variants.find((o) => o.id === v.id);
          if (before && changed(before, v)) await api(`${base}/variants/${v.id}/`, { method: "PATCH", body: variantPayload(v) });
          stockTargets.push({ id: v.id, row: v });
        }
      }
      const keptImages = new Set(filledImages.filter((i) => i.id).map((i) => i.id));
      for (const old of original.images) {
        if (!keptImages.has(old.id)) await api(`${base}/images/${old.id}/`, { method: "DELETE" });
      }
      for (const [position, image] of filledImages.entries()) {
        if (!image.id) await api(`${base}/images/`, { method: "POST", body: { url: image.url.trim(), alt_text: image.alt_text.trim(), position } });
      }
      const failed = await syncStock(stockTargets, (id) => original.variants.find((o) => o.id === id)?.on_hand ?? "");
      const updated = await api(`${base}/`, { method: "PATCH", body: { ...core, status: form.status } });

      const active = updated.variants
        .filter((v) => v.is_active)
        .map((v) => ({ ...v, key: v.id, price: String(v.price), compare_at_price: v.compare_at_price ? String(v.compare_at_price) : "" }));
      const rows = withStock(active, await loadStock(active.map((v) => v.id)));
      setVariants(rows.length ? rows : [blankVariant()]);
      setImages(updated.images.map((i) => ({ ...i, key: String(i.id) })));
      setOriginal({ variants: rows, images: updated.images });
      setForm((f) => ({ ...f, status: updated.status }));
      setState({
        busy: false,
        error: failed.length ? `Stock wasn't saved for ${failed.join(", ")}. Everything else is saved.` : "",
        saved: failed.length === 0,
      });
    } catch (err) {
      setState({ busy: false, error: describe(err), saved: false });
    }
  }

  if (!loaded && !state.error) return <p className="py-16 text-ink-soft">Loading product…</p>;
  if (!loaded) return <Notice>{state.error}</Notice>;

  const justCreated = typeof window !== "undefined" && new URLSearchParams(window.location.search).get("created");

  return (
    <form onSubmit={save} noValidate className="grid gap-6 2xl:grid-cols-[1.5fr_1fr]">
      <section className="raised space-y-5 p-6" aria-labelledby="details-heading">
        <h2 id="details-heading" className="sr-only">Details</h2>
        <Field label="Product name" name="name" value={form.name} onChange={set("name")} required />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Brand" name="brand" value={form.brand} onChange={set("brand")} />
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium">Category</span>
            <select name="category" value={form.category} onChange={set("category")} className="field" required>
              <option value="">Choose a category</option>
              {options.map((o) => <option key={o.slug} value={o.slug}>{o.label}</option>)}
            </select>
          </label>
        </div>
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium">Description</span>
          <textarea name="description" rows={4} value={form.description} onChange={set("description")} className="field" />
        </label>

        <fieldset>
          <legend className="mb-1 font-display text-xl font-bold">Options and prices</legend>
          <p className="mb-4 text-sm text-ink-soft">One row per colour and size you sell. Fill in “Was” to show a discount.</p>
          <div className="space-y-3">
            {variants.map((v, index) => (
              <div key={v.key} className="grid grid-cols-2 items-end gap-2.5 sm:grid-cols-[1.8fr_1fr_.7fr_.9fr_.9fr_.8fr_auto]">
                {[
                  ["sku", "Item code", "e.g. NOVA-X1-BLK"],
                  ["colour", "Colour", "Black"],
                  ["size", "Size", "M"],
                  ["price", "Price (£)", "29.99"],
                  ["compare_at_price", "Was (£)", "optional"],
                  ["on_hand", "In stock", "0"],
                ].map(([field, label, placeholder]) => (
                  <label key={field} className={field === "sku" ? "col-span-2 sm:col-span-1" : ""}>
                    <span className={`mb-1 block text-xs text-ink-soft ${index > 0 ? "sm:sr-only" : ""}`}>{label}</span>
                    <input
                      aria-label={`Option ${index + 1} ${label}`}
                      value={v[field]}
                      onChange={(e) => setVariant(v.key, field, e.target.value)}
                      placeholder={placeholder}
                      inputMode={field.includes("price") ? "decimal" : field === "on_hand" ? "numeric" : undefined}
                      className={`field px-3 py-2 text-sm ${field === "compare_at_price" && v.compare_at_price ? "text-power" : ""}`}
                    />
                  </label>
                ))}
                <button
                  type="button"
                  onClick={() => setVariants((list) => (list.length > 1 ? list.filter((x) => x.key !== v.key) : [blankVariant()]))}
                  className="mb-1 h-9 w-9 rounded-full text-lg font-bold text-power hover:bg-power/10"
                  aria-label={`Remove option ${index + 1}`}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
          <Button type="button" variant="secondary" className="mt-4 px-4 py-2 text-sm" onClick={() => setVariants((list) => [...list, blankVariant()])}>
            + Add an option
          </Button>
        </fieldset>
      </section>

      <div className="grid content-start gap-6 lg:grid-cols-2 2xl:grid-cols-1">
        <section className="raised p-6" aria-labelledby="status-heading">
          <h2 id="status-heading" className="mb-4 text-xl font-bold">Status</h2>
          <div className="inset inline-flex gap-1 rounded-2xl p-1.5" role="radiogroup" aria-label="Status">
            {STATUSES.map(([value, label]) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={form.status === value}
                onClick={() => setForm({ ...form, status: value })}
                className={`rounded-xl px-4 py-2 text-sm font-semibold ${form.status === value ? "btn-metal" : "text-ink-soft hover:text-accent"}`}
              >
                {label}
              </button>
            ))}
          </div>
          <p className="mt-3 text-sm text-ink-soft">Customers only see published products. Publishing needs at least one option with a price.</p>
        </section>

        <section className="raised p-6" aria-labelledby="photos-heading">
          <h2 id="photos-heading" className="mb-1 text-xl font-bold">Photos</h2>
          <p className="mb-4 text-sm text-ink-soft">Paste image links (https://…). The first photo is shown on product cards.</p>
          <div className="space-y-3">
            {images.map((image, index) => (
              <div key={image.key} className="flex items-center gap-3">
                <div className="inset h-14 w-14 shrink-0 overflow-hidden rounded-lg">
                  {image.url && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={image.url} alt="" className="photo h-full w-full object-cover" />
                  )}
                </div>
                <input
                  aria-label={`Photo ${index + 1} link`}
                  value={image.url}
                  readOnly={Boolean(image.id)}
                  onChange={(e) => setImage(image.key, "url", e.target.value)}
                  placeholder="https://…"
                  className={`field px-3 py-2 text-sm ${image.id ? "text-ink-soft" : ""}`}
                />
                <button type="button" onClick={() => setImages((list) => list.filter((x) => x.key !== image.key))}
                  className="h-9 w-9 shrink-0 rounded-full text-lg font-bold text-power hover:bg-power/10" aria-label={`Remove photo ${index + 1}`}>
                  ×
                </button>
              </div>
            ))}
          </div>
          <Button type="button" variant="secondary" className="mt-4 px-4 py-2 text-sm" onClick={() => setImages((list) => [...list, blankImage()])}>
            + Add a photo
          </Button>
        </section>

        <div className="space-y-4 lg:col-span-2 2xl:col-span-1">
          {justCreated && !state.saved && !state.error && <Notice tone="success">Product created. You can keep editing it here.</Notice>}
          {state.saved && <Notice tone="success">Changes saved.</Notice>}
          <Notice>{state.error}</Notice>
          <div className="flex gap-4">
            <Button type="submit" busy={state.busy} className="flex-1 py-3.5 text-lg">
              {state.busy ? "Saving…" : isNew ? "Create product" : "Save changes"}
            </Button>
            <Button type="button" variant="secondary" onClick={() => router.push(listHref)}>Back</Button>
          </div>
        </div>
      </div>
    </form>
  );
}
