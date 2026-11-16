"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { BODY_MAX, BODY_MIN, TITLE_MAX, ratingLabel, reviewDate, starBars, validateReview } from "@/lib/reviews";
import { useSession } from "@/lib/session";

import Stars, { STAR_PATH } from "./Stars";
import { Button, Field, Notice } from "./ui";

const STAR_VALUES = [1, 2, 3, 4, 5];

function StarPicker({ value, onChange, error }) {
  return (
    <fieldset>
      <legend className="mb-1.5 text-sm font-medium">Your rating</legend>
      <div className="flex gap-2">
        {STAR_VALUES.map((star) => (
          <button
            key={star}
            type="button"
            aria-label={`${star} ${star === 1 ? "star" : "stars"}`}
            aria-pressed={value === star}
            onClick={() => onChange(star)}
            className={`grid h-11 w-11 place-items-center rounded-xl ${value === star ? "pressed" : "raised-sm hover:text-accent"}`}
          >
            <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true">
              <path d={STAR_PATH} fill={star <= value ? "var(--accent)" : "var(--line)"} />
            </svg>
          </button>
        ))}
      </div>
      {error && <span className="mt-1.5 block text-sm font-medium text-power">{error}</span>}
    </fieldset>
  );
}

export default function ProductReviews({ slug, productName }) {
  const { user } = useSession();
  // The public summary and newest reviews, and (when signed in) the customer's own review and whether they may write one.
  const [list, setList] = useState(null);
  const [mine, setMine] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [form, setForm] = useState(null);
  const [errors, setErrors] = useState({});
  const [state, setState] = useState({ busy: false, error: "", notice: "" });

  const load = useCallback(async () => {
    try {
      setList(await api(`/api/v1/products/${slug}/reviews/`, { auth: false }));
      setLoadError("");
    } catch (err) {
      setLoadError(err.message);
    }
  }, [slug]);

  const loadMine = useCallback(async () => {
    if (!user) {
      setMine(null);
      return;
    }
    try {
      setMine(await api(`/api/v1/products/${slug}/reviews/mine/`));
    } catch (err) {
      setState((current) => ({ ...current, error: err.message }));
    }
  }, [slug, user]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    loadMine();
  }, [loadMine]);

  function openForm(review) {
    setErrors({});
    setState({ busy: false, error: "", notice: "" });
    setForm(review
      ? { rating: review.rating, title: review.title, body: review.body }
      : { rating: 0, title: "", body: "" });
  }

  async function submit(event) {
    event.preventDefault();
    const checked = validateReview(form);
    setErrors(checked.errors);
    if (!checked.ok) return;

    const editing = Boolean(mine?.review);
    setState({ busy: true, error: "", notice: "" });
    try {
      await api(`/api/v1/products/${slug}/reviews/${editing ? "mine/" : ""}`, {
        method: editing ? "PUT" : "POST",
        body: checked.payload,
      });
      setForm(null);
      setState({ busy: false, error: "", notice: editing ? "Your review is updated." : "Thanks, your review is posted." });
      await Promise.all([load(), loadMine()]);
    } catch (err) {
      setState({ busy: false, error: err.message, notice: "" });
    }
  }

  const summary = list?.summary;
  const bars = starBars(summary?.distribution, summary?.count);
  const bodyNeedsWork = Boolean(errors.body);

  return (
    <section aria-labelledby="reviews-heading" className="space-y-8">
      <div>
        <h2 id="reviews-heading" className="text-2xl font-bold">Customer reviews</h2>
        <p className="mt-1 text-ink-soft">{ratingLabel(summary?.average, summary?.count)}</p>
      </div>

      <Notice tone="error">{loadError}</Notice>

      {list && (
        <div className="grid gap-8 md:grid-cols-[260px_1fr]">
          <div className="raised space-y-3 p-6">
            {bars.map((bar) => (
              <div key={bar.stars} className="flex items-center gap-3 text-sm">
                <span className="w-14 text-ink-soft">{bar.stars} {bar.stars === 1 ? "star" : "stars"}</span>
                <div className="inset h-2.5 flex-1 overflow-hidden rounded-full">
                  <div className="h-full rounded-full bg-accent" style={{ width: `${bar.percent}%` }} />
                </div>
                <span className="w-8 text-right tabular-nums text-ink-soft">{bar.count}</span>
              </div>
            ))}
          </div>

          <div className="space-y-4">
            {list.results.length === 0 && (
              <p className="raised p-6 text-ink-soft">No reviews yet. Verified buyers can be the first to write one.</p>
            )}
            {list.results.map((review) => (
              <article key={review.id} className="raised p-6">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Stars value={review.rating} label={`${review.rating} out of 5 stars`} />
                  <span className="text-sm font-semibold text-accent">Verified purchase</span>
                </div>
                <h3 className="mt-3 font-semibold">{review.title}</h3>
                <p className="mt-2 leading-relaxed text-ink-soft">{review.body}</p>
                <p className="mt-3 text-sm text-ink-soft">{reviewDate(review.created_at)}</p>
              </article>
            ))}
          </div>
        </div>
      )}

      <div className="space-y-4">
        <Notice tone="success">{state.notice}</Notice>
        <Notice tone="error">{state.error}</Notice>

        {!user && (
          <Notice tone="info">
            Sign in to write a review.{" "}
            <Link href="/login" className="font-semibold text-accent underline-offset-4 hover:underline">Sign in</Link>
          </Notice>
        )}

        {user && mine && !mine.review && !mine.verified && (
          <Notice tone="info">
            Only customers who bought this product can review it. The form opens once a delivered order includes it.
          </Notice>
        )}

        {user && mine?.review && !form && (
          <Button variant="secondary" onClick={() => openForm(mine.review)}>Edit your review</Button>
        )}

        {user && mine && !mine.review && mine.verified && !form && (
          <Button onClick={() => openForm(null)}>Write a review</Button>
        )}

        {form && (
          <form onSubmit={submit} noValidate aria-label={`Review of ${productName}`} className="raised max-w-2xl space-y-5 p-6">
            <StarPicker value={form.rating} onChange={(rating) => setForm({ ...form, rating })} error={errors.rating} />
            <Field
              label="Title"
              id="review-title"
              maxLength={TITLE_MAX}
              value={form.title}
              onChange={(event) => setForm({ ...form, title: event.target.value })}
              error={errors.title}
              hint={`${form.title.length}/${TITLE_MAX}`}
            />
            <label htmlFor="review-body" className="block">
              <span className="mb-1.5 block text-sm font-medium">Review</span>
              <textarea
                id="review-body"
                rows={5}
                maxLength={BODY_MAX}
                value={form.body}
                onChange={(event) => setForm({ ...form, body: event.target.value })}
                aria-invalid={bodyNeedsWork ? true : undefined}
                aria-describedby="review-body-hint"
                className="field"
              />
              <span
                id="review-body-hint"
                className={`mt-1.5 block text-sm ${bodyNeedsWork ? "font-medium text-power" : "text-ink-soft"}`}
              >
                {errors.body || `At least ${BODY_MIN} characters · ${form.body.length}/${BODY_MAX}`}
              </span>
            </label>
            <div className="flex flex-wrap justify-end gap-3">
              <Button type="button" variant="secondary" onClick={() => setForm(null)}>Cancel</Button>
              <Button type="submit" busy={state.busy}>{mine?.review ? "Save changes" : "Post review"}</Button>
            </div>
          </form>
        )}
      </div>
    </section>
  );
}
