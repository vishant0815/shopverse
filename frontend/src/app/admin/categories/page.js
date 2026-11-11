"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import PanelShell, { PageTitle } from "@/components/panel/PanelShell";
import { Button, Field, Notice } from "@/components/ui";
import { api } from "@/lib/api";

// Top-level categories first, each followed by its children.
function ordered(categories) {
  const byParent = {};
  for (const c of categories) (byParent[c.parent || ""] ||= []).push(c);
  const sort = (list) => [...list].sort((a, b) => a.position - b.position || a.name.localeCompare(b.name));
  const rows = [];
  for (const top of sort(byParent[""] || [])) {
    rows.push({ ...top, depth: 0 });
    for (const child of sort(byParent[top.slug] || [])) rows.push({ ...child, depth: 1 });
  }
  return rows;
}

function CategoryRow({ category, onSaved, onError }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(category.name);
  const [busy, setBusy] = useState(false);

  async function patch(body) {
    setBusy(true);
    try {
      await api(`/api/v1/categories/${category.slug}/`, { method: "PATCH", body });
      setEditing(false);
      await onSaved();
    } catch (err) {
      onError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className={`flex flex-wrap items-center justify-between gap-3 border-t border-line py-3 ${category.depth ? "pl-8" : ""}`}>
      {editing ? (
        <form className="flex flex-1 items-center gap-2" onSubmit={(e) => { e.preventDefault(); if (name.trim()) patch({ name: name.trim() }); }}>
          <label htmlFor={`rename-${category.slug}`} className="sr-only">New name for {category.name}</label>
          <input id={`rename-${category.slug}`} value={name} onChange={(e) => setName(e.target.value)} className="field max-w-xs px-3 py-1.5" autoFocus />
          <Button type="submit" className="px-3 py-1.5 text-sm" busy={busy}>Save</Button>
          <Button type="button" variant="quiet" className="text-sm" onClick={() => { setEditing(false); setName(category.name); }}>Cancel</Button>
        </form>
      ) : (
        <div className={category.is_active ? "" : "opacity-55"}>
          <span className={category.depth ? "" : "font-display text-lg font-bold"}>
            {category.depth ? "↳ " : ""}{category.name}
          </span>
          <span className="ml-2 font-mono text-xs text-ink-soft">/{category.slug}</span>
          {!category.is_active && <span className="ml-3 text-sm font-semibold text-power">Hidden</span>}
        </div>
      )}
      {!editing && (
        <div className="flex items-center gap-4 text-sm font-semibold">
          <button onClick={() => setEditing(true)} className="text-accent hover:underline">Rename</button>
          <button onClick={() => patch({ is_active: !category.is_active })} disabled={busy}
            className={`${category.is_active ? "text-power" : "text-accent"} hover:underline disabled:opacity-50`}>
            {category.is_active ? "Hide" : "Show"}
          </button>
        </div>
      )}
    </li>
  );
}

function Categories() {
  const [categories, setCategories] = useState(null);
  const [form, setForm] = useState({ name: "", parent: "" });
  const [error, setError] = useState("");
  const [created, setCreated] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setCategories(await api("/api/v1/categories/"));
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const rows = useMemo(() => (categories ? ordered(categories) : []), [categories]);
  const parents = rows.filter((c) => c.depth === 0);

  async function add(event) {
    event.preventDefault();
    if (!form.name.trim()) return setError("Give the category a name.");
    setBusy(true);
    setError("");
    try {
      const category = await api("/api/v1/categories/", {
        method: "POST",
        body: { name: form.name.trim(), parent: form.parent || null },
      });
      setCreated(`Added “${category.name}”.`);
      setForm({ name: "", parent: form.parent });
      await load();
    } catch (err) {
      // Either the generated slug is taken, or the same name already exists under that parent.
      const duplicate = err.data?.slug || String(err.data?.non_field_errors || "").includes("unique");
      setError(duplicate ? "A category with that name already exists." : err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageTitle title="Categories" lede="Hidden categories disappear from the shop menu and can't be picked for new products." />
      <div className="grid gap-6 xl:grid-cols-[1fr_320px]">
        <section className="raised p-6" aria-labelledby="list-heading">
          <h2 id="list-heading" className="mb-2 text-xl font-bold">All categories</h2>
          {!categories ? (
            <p className="text-ink-soft">Loading categories…</p>
          ) : (
            <ul>
              {rows.map((category) => (
                <CategoryRow key={category.slug} category={category} onSaved={load} onError={setError} />
              ))}
            </ul>
          )}
        </section>
        <aside>
          <form onSubmit={add} className="raised space-y-4 p-6" noValidate>
            <h2 className="text-xl font-bold">Add a category</h2>
            <Field label="Name" name="name" value={form.name} onChange={(e) => { setForm({ ...form, name: e.target.value }); setCreated(""); }} />
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium">Inside</span>
              <select value={form.parent} onChange={(e) => setForm({ ...form, parent: e.target.value })} className="field">
                <option value="">Nothing (top level)</option>
                {parents.map((p) => <option key={p.slug} value={p.slug}>{p.name}</option>)}
              </select>
            </label>
            <Notice tone="success">{created}</Notice>
            <Notice>{error}</Notice>
            <Button type="submit" busy={busy} className="w-full">{busy ? "Adding…" : "Add category"}</Button>
          </form>
        </aside>
      </div>
    </>
  );
}

export default function AdminCategoriesPage() {
  return (
    <PanelShell role="admin">
      <Categories />
    </PanelShell>
  );
}
