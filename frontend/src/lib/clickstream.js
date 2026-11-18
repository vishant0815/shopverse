// Storefront analytics: builds the events the collector accepts and sends them in batches.
//
// Events wait a few seconds so they go out together, and go at once when the page is hidden.
// Every event carries its own id, so a batch that has to be sent again is counted once.
// Analytics is best effort: a failure here never changes what the shopper sees.

import { api } from "./api.js";

export const SESSION_KEY = "shopverse.session";
const FLUSH_AFTER_MS = 5000;
const MAX_BATCH = 100; // the collector takes at most this many per request
const MAX_QUEUE = 500; // while sending keeps failing, the oldest events are dropped first

export function randomId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  // Browsers only offer randomUUID on secure pages; this is good enough for analytics ids.
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

// An anonymous visitor id, kept in localStorage so it lasts across visits. It is not linked
// to an IP address. If storage is blocked, the id lasts only for this page visit.
export function sessionId(storage = globalThis.localStorage) {
  try {
    const existing = storage.getItem(SESSION_KEY);
    if (existing && /^[A-Za-z0-9-]{8,64}$/.test(existing)) return existing;
    const fresh = randomId();
    storage.setItem(SESSION_KEY, fresh);
    return fresh;
  } catch {
    return randomId();
  }
}

export function buildEvent(type, fields, { session, now = new Date() }) {
  return { event_id: randomId(), type, occurred_at: now.toISOString(), session_id: session, ...fields };
}

// Where a product view came from, read from the page the shopper came from.
export function productSource(referrer, origin = globalThis.location?.origin) {
  try {
    const url = new URL(referrer);
    if (origin && url.origin !== origin) return "direct";
    if (url.pathname.startsWith("/products") && url.searchParams.get("search")) return "search";
    if (url.pathname.startsWith("/products") && url.searchParams.get("category")) return "category";
  } catch {
    // No referrer, or not a URL: treat as a direct visit.
  }
  return "direct";
}

// A 4xx means the collector rejected this batch for good (a bad event), so retrying can't help.
// Network errors and server errors are retried, as is 429.
function permanentlyRejected(error) {
  const status = error?.status;
  return Number.isInteger(status) && status >= 400 && status < 500 && status !== 429;
}

export function createTracker({
  send,
  session,
  flushAfterMs = FLUSH_AFTER_MS,
  setTimer = globalThis.setTimeout,
  clearTimer = globalThis.clearTimeout,
  now = () => new Date(),
}) {
  let queue = [];
  let timer = null;

  function schedule() {
    if (!timer) {
      timer = setTimer(() => {
        timer = null;
        return flush();
      }, flushAfterMs);
    }
  }

  function track(type, fields) {
    queue.push(buildEvent(type, fields, { session, now: now() }));
    if (queue.length > MAX_QUEUE) queue = queue.slice(-MAX_QUEUE);
    schedule();
  }

  async function flush() {
    if (timer) {
      clearTimer(timer);
      timer = null;
    }
    if (!queue.length) return;

    const batch = queue.slice(0, MAX_BATCH);
    queue = queue.slice(batch.length);
    try {
      await send(batch);
    } catch (error) {
      if (!permanentlyRejected(error)) {
        // Back to the front of the queue. The events keep their ids, so a resend is counted once.
        queue = [...batch, ...queue].slice(-MAX_QUEUE);
      }
    }
    if (queue.length) schedule();
  }

  return { track, flush, pending: () => queue.length };
}

async function sendBatch(events) {
  await api("/api/v1/clickstream/events", { method: "POST", body: { events }, retry: false });
}

let shared = null;

// The one tracker for the whole page. Only call this in the browser.
export function tracker() {
  if (!shared) {
    shared = createTracker({ send: sendBatch, session: sessionId() });
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") shared.flush();
    });
  }
  return shared;
}
