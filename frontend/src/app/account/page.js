"use client";

import { useEffect, useState } from "react";

import AddressForm, { emptyAddress } from "@/components/AddressForm";
import RequireSignIn from "@/components/RequireSignIn";
import { Button, Field, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

function errorsFrom(err) {
  if (err.status !== 400 || !err.data || typeof err.data !== "object") return {};
  return Object.fromEntries(Object.entries(err.data).map(([k, v]) => [k, [].concat(v).join(" ")]));
}

function Profile() {
  const { user, setUser } = useSession();
  const [form, setForm] = useState({ first_name: user.first_name, last_name: user.last_name, phone: user.phone });
  const [state, setState] = useState({ busy: false, saved: false, errors: {}, error: "" });

  async function save(event) {
    event.preventDefault();
    setState({ busy: true, saved: false, errors: {}, error: "" });
    try {
      setUser(await api("/api/v1/users/me/", { method: "PATCH", body: form }));
      setState({ busy: false, saved: true, errors: {}, error: "" });
    } catch (err) {
      setState({ busy: false, saved: false, errors: errorsFrom(err), error: err.status === 400 ? "" : err.message });
    }
  }

  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  return (
    <form onSubmit={save} className="space-y-4">
      <h2 className="text-2xl font-bold">Your details</h2>
      <p className="text-ink-soft">
        Signed in as {user.email}
        {user.role === "seller" ? ", with a seller account" : ""}.
      </p>
      <Notice>{state.error}</Notice>
      {state.saved && <Notice tone="success">Details saved.</Notice>}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="First name" name="first_name" value={form.first_name} onChange={set("first_name")} error={state.errors.first_name} />
        <Field label="Last name" name="last_name" value={form.last_name} onChange={set("last_name")} error={state.errors.last_name} />
        <Field label="Phone" name="phone" type="tel" value={form.phone} onChange={set("phone")} error={state.errors.phone} />
      </div>
      <Button type="submit" busy={state.busy}>{state.busy ? "Saving…" : "Save details"}</Button>
    </form>
  );
}

function Addresses() {
  const [addresses, setAddresses] = useState(null);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState(emptyAddress);
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");

  const load = () => api("/api/v1/addresses/").then((d) => setAddresses(d.results)).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  async function add(event) {
    event.preventDefault();
    setErrors({});
    try {
      await api("/api/v1/addresses/", { method: "POST", body: draft });
      setAdding(false);
      setDraft(emptyAddress);
      load();
    } catch (err) {
      setErrors(errorsFrom(err));
      if (err.status !== 400) setError(err.message);
    }
  }

  async function act(id, request) {
    setError("");
    try {
      await api(`/api/v1/addresses/${id}/`, request);
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <section className="space-y-4" aria-labelledby="addresses-heading">
      <h2 id="addresses-heading" className="text-2xl font-bold">Saved addresses</h2>
      <Notice>{error}</Notice>
      {addresses === null ? (
        <p className="text-ink-soft">Loading…</p>
      ) : addresses.length === 0 && !adding ? (
        <p className="text-ink-soft">No saved addresses yet. Add one here or at checkout.</p>
      ) : (
        <ul className="space-y-3">
          {addresses.map((address) => (
            <li key={address.id} className="flex flex-wrap items-start justify-between gap-3 border border-line bg-white p-4">
              <div>
                <p className="font-semibold">
                  {address.full_name}
                  {address.is_default && <span className="ml-2 rounded-sm bg-sticker px-1.5 text-sm">Default</span>}
                </p>
                <p className="text-ink-soft">{[address.line1, address.line2, address.city, address.postcode].filter(Boolean).join(", ")}</p>
              </div>
              <div className="flex gap-4 text-sm">
                {!address.is_default && (
                  <button onClick={() => act(address.id, { method: "PATCH", body: { is_default: true } })} className="text-cobalt hover:underline">
                    Make default
                  </button>
                )}
                <button onClick={() => act(address.id, { method: "DELETE" })} className="text-sale hover:underline">Delete</button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {adding ? (
        <form onSubmit={add} className="space-y-4 border border-ink bg-white p-5">
          <AddressForm value={draft} onChange={setDraft} errors={errors} />
          <div className="flex gap-3">
            <Button type="submit">Save address</Button>
            <Button type="button" variant="quiet" onClick={() => setAdding(false)}>Cancel</Button>
          </div>
        </form>
      ) : (
        <Button variant="secondary" onClick={() => setAdding(true)}>Add an address</Button>
      )}
    </section>
  );
}

export default function AccountPage() {
  return (
    <RequireSignIn>
      <div className="max-w-3xl space-y-12">
        <h1 className="text-4xl font-extrabold">Your account</h1>
        <Profile />
        <Addresses />
      </div>
    </RequireSignIn>
  );
}
