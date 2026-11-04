"use client";

import { useEffect, useState } from "react";

import PanelShell, { PageTitle } from "@/components/panel/PanelShell";
import SalesTable from "@/components/panel/SalesTable";
import { Button, Notice } from "@/components/ui";
import { api } from "@/lib/api";

const FILTERS = [
  ["", "All"],
  ["paid", "To ship"],
  ["shipped", "Shipped"],
  ["delivered", "Delivered"],
  ["pending_payment", "Awaiting payment"],
  ["cancelled", "Cancelled"],
];

function Sales() {
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const query = new URLSearchParams({ page: String(page), ...(status ? { status } : {}) });
    api(`/api/v1/seller/sales/?${query}`).then(setData).catch((err) => setError(err.message));
  }, [status, page]);

  return (
    <>
      <PageTitle title="Sales" lede="Every order line for your products. Buyer details stay private." />
      <div className="mb-6 flex flex-wrap gap-3" role="group" aria-label="Filter by status">
        {FILTERS.map(([value, label]) => (
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
      <Notice>{error}</Notice>
      <section className="raised p-5">
        {!data ? (
          <p className="text-ink-soft">Loading sales…</p>
        ) : data.results.length === 0 ? (
          <p className="text-ink-soft">No sales here yet.</p>
        ) : (
          <SalesTable sales={data.results} />
        )}
      </section>
      {data && (data.next || data.previous) && (
        <div className="mt-6 flex items-center gap-4">
          <Button variant="secondary" disabled={!data.previous} onClick={() => setPage((p) => p - 1)}>Previous</Button>
          <span className="text-ink-soft">Page {page}</span>
          <Button variant="secondary" disabled={!data.next} onClick={() => setPage((p) => p + 1)}>Next</Button>
        </div>
      )}
    </>
  );
}

export default function SellerSalesPage() {
  return (
    <PanelShell role="seller">
      <Sales />
    </PanelShell>
  );
}
