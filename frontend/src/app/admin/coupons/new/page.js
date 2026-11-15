"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import PanelShell, { PageTitle } from "@/components/panel/PanelShell";
import { Button, Field, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { couponRequest } from "@/lib/coupon";

const EMPTY = {
  code: "",
  kind: "percent",
  value: "",
  min_subtotal: "",
  starts_at: "",
  ends_at: "",
  usage_limit: "",
  per_customer_limit: "1",
};

const KINDS = [
  ["percent", "Percent off"],
  ["fixed", "Fixed amount off"],
];

function NewCoupon() {
  const router = useRouter();
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState({});

  // Props for a field that reads and writes one key of the form, and shows its own error.
  const field = (name) => ({
    name,
    value: form[name],
    error: fieldErrors[name],
    onChange: (event) => setForm((current) => ({ ...current, [name]: event.target.value })),
  });

  async function create(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setFieldErrors({});
    try {
      await api("/api/v1/admin/coupons/", { method: "POST", body: couponRequest(form) });
      router.push("/admin/coupons");
    } catch (err) {
      if (err.status === 400 && err.data && typeof err.data === "object") {
        const { non_field_errors: general, ...fields } = err.data;
        setFieldErrors(Object.fromEntries(Object.entries(fields).map(([key, value]) => [key, [].concat(value).join(" ")])));
        if (general) setError([].concat(general).join(" "));
      } else {
        setError(err.message);
      }
      setBusy(false);
    }
  }

  const percent = form.kind === "percent";

  return (
    <PanelShell role="admin">
      <PageTitle
        title="New coupon"
        lede="Shoppers type this code at the basket. Shipping is judged before the discount, so a code never adds a shipping fee."
      />

      {error && <div className="mb-4"><Notice>{error}</Notice></div>}

      <form onSubmit={create} noValidate className="raised max-w-2xl space-y-6 p-7">
        <Field
          label="Code"
          maxLength={40}
          required
          hint="Letters and numbers. Shoppers can type it in any case."
          {...field("code")}
        />

        <div>
          <span className="mb-1.5 block text-sm font-medium">Discount</span>
          <div role="group" aria-label="Discount type" className="flex gap-3">
            {KINDS.map(([value, label]) => (
              <button
                key={value}
                type="button"
                aria-pressed={form.kind === value}
                onClick={() => setForm((current) => ({ ...current, kind: value }))}
                className={`flex-1 rounded-xl px-4 py-3 font-semibold ${form.kind === value ? "pressed text-accent" : "raised text-ink-soft hover:text-accent"}`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="grid gap-5 sm:grid-cols-2">
          <Field
            label={percent ? "Percentage" : "Amount (£)"}
            inputMode="decimal"
            hint={percent ? "1 to 100." : "More than zero, and no more than the basket total."}
            {...field("value")}
          />
          <Field
            label="Minimum basket (£)"
            inputMode="decimal"
            hint="Checked before the discount. Leave empty for none."
            {...field("min_subtotal")}
          />
          <Field label="Starts" type="datetime-local" hint="Leave empty to start straight away." {...field("starts_at")} />
          <Field label="Ends" type="datetime-local" hint="Leave empty for no end date." {...field("ends_at")} />
          <Field label="Total uses" type="number" min={1} hint="Leave empty for no limit." {...field("usage_limit")} />
          <Field label="Uses per customer" type="number" min={1} hint="Leave empty for no limit." {...field("per_customer_limit")} />
        </div>

        <p className="text-sm leading-relaxed text-ink-soft">
          A fixed amount can&apos;t take more than the basket total. A cancelled order gives its use back.
        </p>

        <div className="flex justify-end gap-3">
          <Link href="/admin/coupons" className="btn btn-soft">Cancel</Link>
          <Button type="submit" busy={busy}>{busy ? "Creating…" : "Create coupon"}</Button>
        </div>
      </form>
    </PanelShell>
  );
}

export default function NewCouponPage() {
  return <NewCoupon />;
}
