// Product reviews: the limits the products service enforces too, how a rating reads, and the form check.

export const TITLE_MAX = 120;
export const BODY_MIN = 20;
export const BODY_MAX = 2000;

// Checks the form before it is sent. Text is trimmed first, so spaces alone don't count as a title or review.
export function validateReview({ rating, title, body }) {
  const errors = {};
  if (!Number.isInteger(rating) || rating < 1 || rating > 5) {
    errors.rating = "Choose a rating from 1 to 5 stars.";
  }
  const cleanTitle = (title || "").trim();
  if (!cleanTitle) {
    errors.title = "Add a title.";
  } else if (cleanTitle.length > TITLE_MAX) {
    errors.title = `Keep the title under ${TITLE_MAX} characters.`;
  }
  const cleanBody = (body || "").trim();
  if (cleanBody.length < BODY_MIN) {
    errors.body = `Write at least ${BODY_MIN} characters.`;
  } else if (cleanBody.length > BODY_MAX) {
    errors.body = `Keep the review under ${BODY_MAX} characters.`;
  }
  return {
    ok: Object.keys(errors).length === 0,
    errors,
    payload: { rating, title: cleanTitle, body: cleanBody },
  };
}

// "4.7 · 3 reviews", or "No reviews yet" before the first one.
export function ratingLabel(average, count) {
  if (!count || average == null) return "No reviews yet";
  const noun = count === 1 ? "review" : "reviews";
  return `${Number(average).toFixed(1)} · ${count} ${noun}`;
}

// One bar per star level, five stars first, each with its share of the reviews.
export function starBars(distribution = {}, count = 0) {
  return [5, 4, 3, 2, 1].map((stars) => {
    const reviews = distribution[String(stars)] || 0;
    return { stars, count: reviews, percent: count ? Math.round((reviews / count) * 100) : 0 };
  });
}

// The day a review was written, in London time, as the shop shows its other dates.
export function reviewDate(iso) {
  return new Date(iso).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Europe/London",
  });
}
