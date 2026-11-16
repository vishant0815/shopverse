"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import Stars from "@/components/Stars";
import PanelShell, { PageTitle } from "@/components/panel/PanelShell";
import { Button, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { reviewDate } from "@/lib/reviews";

const TABS = [
  ["all", "All"],
  ["visible", "Visible"],
  ["hidden", "Hidden"],
];

export default function AdminReviews() {
  const [tab, setTab] = useState("all");
  const [query, setQuery] = useState("");
  const [reviews, setReviews] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(null);

  const load = useCallback(async () => {
    try {
      const data = await api(`/api/v1/admin/reviews/${tab === "all" ? "" : `?status=${tab}`}`);
      setReviews(data.results);
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }, [tab]);

  useEffect(() => {
    load();
  }, [load]);

  // Filters the loaded page by product, title or text, so an admin can find one review quickly.
  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (reviews || []).filter((review) =>
      !needle || `${review.product_name} ${review.title} ${review.body}`.toLowerCase().includes(needle),
    );
  }, [reviews, query]);

  async function setStatus(review, status) {
    setBusy(review.id);
    setError("");
    setNotice("");
    try {
      await api(`/api/v1/admin/reviews/${review.id}/`, { method: "PATCH", body: { status } });
      setNotice(status === "hidden"
        ? `The review of ${review.product_name} is hidden. It no longer counts towards the rating.`
        : `The review of ${review.product_name} is visible again.`);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <PanelShell role="admin">
      <PageTitle
        title="Reviews"
        lede="Hide a review to take it off the product page and out of its rating. Showing it again puts it back."
      />

      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-wrap gap-2.5" role="group" aria-label="Filter reviews by status">
          {TABS.map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={tab === value}
              onClick={() => setTab(value)}
              className={`rounded-xl px-4 py-2 font-semibold ${tab === value ? "pressed text-accent" : "raised text-ink-soft hover:text-accent"}`}
            >
              {label}
            </button>
          ))}
        </div>
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium">Search reviews</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Product, title or text"
            className="field w-72"
          />
        </label>
      </div>

      <div className="mb-4 space-y-3">
        <Notice tone="error">{error}</Notice>
        <Notice tone="success">{notice}</Notice>
      </div>

      {reviews === null && !error && <p className="text-ink-soft">Loading reviews…</p>}
      {reviews && rows.length === 0 && <p className="raised p-6 text-ink-soft">No reviews here.</p>}

      {reviews && rows.length > 0 && (
        <div className="raised overflow-x-auto px-5">
          <table className="w-full min-w-[860px] border-collapse text-left text-[15px]">
            <thead>
              <tr className="text-sm text-ink-soft">
                <th scope="col" className="py-4 pr-4 font-semibold">Product</th>
                <th scope="col" className="py-4 pr-4 font-semibold">Rating</th>
                <th scope="col" className="py-4 pr-4 font-semibold">Review</th>
                <th scope="col" className="py-4 pr-4 font-semibold">Date</th>
                <th scope="col" className="py-4 pr-4 font-semibold">Status</th>
                <th scope="col" className="py-4 text-right font-semibold"><span className="sr-only">Action</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((review) => {
                const visible = review.status === "visible";
                return (
                  <tr key={review.id} className="border-t border-[var(--line)] align-top">
                    <td className="py-4 pr-4">{review.product_name}</td>
                    <td className="py-4 pr-4"><Stars value={review.rating} label={`${review.rating} out of 5 stars`} size={16} /></td>
                    <td className="py-4 pr-4">
                      <p className="font-semibold">{review.title}</p>
                      <p className="mt-1 max-w-md text-sm text-ink-soft">{review.body}</p>
                    </td>
                    <td className="whitespace-nowrap py-4 pr-4 text-ink-soft">{reviewDate(review.created_at)}</td>
                    <td className={`py-4 pr-4 font-semibold ${visible ? "text-accent" : "text-ink-soft"}`}>
                      {visible ? "Visible" : "Hidden"}
                    </td>
                    <td className="py-4 text-right">
                      <Button
                        variant="secondary"
                        busy={busy === review.id}
                        onClick={() => setStatus(review, visible ? "hidden" : "visible")}
                      >
                        {visible ? "Hide" : "Show"}
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </PanelShell>
  );
}
