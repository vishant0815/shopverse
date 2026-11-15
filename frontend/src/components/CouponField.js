"use client";

import { useState } from "react";

import { api } from "@/lib/api";
import { discountLabel, normalizeCode } from "@/lib/coupon";

// The basket's coupon. With no code applied it shows a box to type one in. With a code
// applied it shows the code and its discount. A code that has stopped working stays here with
// the reason, so the shopper can see why nothing came off.
export default function CouponField({ coupon, onCart }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function apply(event) {
    event.preventDefault();
    const entered = normalizeCode(code);
    if (!entered) {
      setError("Type a code first.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      onCart(await api("/api/v1/cart/coupon/", { method: "PUT", body: { code: entered } }));
      setCode("");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setError("");
    try {
      onCart(await api("/api/v1/cart/coupon/", { method: "DELETE" }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (coupon) {
    return (
      <div className="mb-5">
        <div className="inset flex items-center justify-between gap-3 rounded-xl p-3.5">
          <div>
            <p className="text-sm text-ink-soft">Coupon</p>
            <p className="font-display font-bold tracking-wide">
              {coupon.code}
              {coupon.valid && <span className="ml-2 text-sm font-medium text-accent">{discountLabel(coupon)}</span>}
            </p>
          </div>
          <button
            type="button"
            onClick={remove}
            disabled={busy}
            className="text-sm font-semibold text-ink-soft underline hover:text-accent disabled:opacity-40"
          >
            Remove
          </button>
        </div>
        {!coupon.valid && (
          <p role="alert" className="mt-2 text-sm font-semibold text-power">{coupon.message}</p>
        )}
        {error && <p role="alert" className="mt-2 text-sm font-semibold text-power">{error}</p>}
      </div>
    );
  }

  return (
    <form onSubmit={apply} noValidate className="mb-5">
      <label htmlFor="coupon-code" className="mb-1.5 block text-sm font-medium">Coupon code</label>
      <div className="flex gap-2.5">
        <input
          id="coupon-code"
          name="coupon"
          className="field"
          value={code}
          onChange={(event) => setCode(event.target.value)}
          autoComplete="off"
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? "coupon-error" : undefined}
        />
        <button type="submit" disabled={busy} className="btn btn-soft shrink-0">
          {busy ? "Applying…" : "Apply"}
        </button>
      </div>
      {error && (
        <p id="coupon-error" role="alert" className="mt-2 text-sm font-semibold text-power">{error}</p>
      )}
    </form>
  );
}
