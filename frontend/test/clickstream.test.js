import { describe, test } from "node:test";
import assert from "node:assert/strict";

import { buildEvent, createTracker, productSource, sessionId, SESSION_KEY } from "../src/lib/clickstream.js";

function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (key) => (data.has(key) ? data.get(key) : null),
    setItem: (key, value) => data.set(key, String(value)),
    data,
  };
}

// Timers the test fires by hand, so batching can be checked without waiting.
function manualTimers() {
  let pending = null;
  return {
    setTimer: (fn) => {
      pending = fn;
      return "timer";
    },
    clearTimer: () => {
      pending = null;
    },
    fire: () => {
      const fn = pending;
      pending = null;
      return fn?.();
    },
    scheduled: () => pending !== null,
  };
}

function httpError(status) {
  return Object.assign(new Error(`status ${status}`), { status });
}

describe("visitor session id", () => {
  test("is created once and reused on later visits", () => {
    const storage = memoryStorage();

    const first = sessionId(storage);
    const second = sessionId(storage);

    assert.match(first, /^[A-Za-z0-9-]{8,64}$/);
    assert.equal(second, first);
    assert.equal(storage.data.get(SESSION_KEY), first);
  });

  test("a stored value with odd characters is replaced", () => {
    const storage = memoryStorage({ [SESSION_KEY]: "bad value; drop" });

    const id = sessionId(storage);

    assert.notEqual(id, "bad value; drop");
    assert.match(id, /^[A-Za-z0-9-]{8,64}$/);
  });

  test("blocked storage still gives an id for the visit", () => {
    const blocked = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    };

    assert.match(sessionId(blocked), /^[A-Za-z0-9-]{8,64}$/);
  });
});

describe("events", () => {
  test("carry an id, the time and the session, plus the fields for their type", () => {
    const now = new Date("2026-11-18T12:00:00.000Z");

    const event = buildEvent("search", { query: "lamp", result_count: 3 }, { session: "s-1234567", now });

    assert.match(event.event_id, /^[0-9a-f-]{36}$/);
    assert.deepEqual(
      { ...event, event_id: undefined },
      { event_id: undefined, type: "search", occurred_at: "2026-11-18T12:00:00.000Z", session_id: "s-1234567", query: "lamp", result_count: 3 },
    );
  });

  test("each event gets its own id", () => {
    const a = buildEvent("search", {}, { session: "s-1234567" });
    const b = buildEvent("search", {}, { session: "s-1234567" });

    assert.notEqual(a.event_id, b.event_id);
  });
});

describe("product view source", () => {
  const origin = "https://shop.example";

  test("a search results page counts as search", () => {
    assert.equal(productSource(`${origin}/products?search=lamp&page=2`, origin), "search");
  });

  test("a category page counts as category", () => {
    assert.equal(productSource(`${origin}/products?category=lighting`, origin), "category");
  });

  test("anything else is direct, including other sites and no referrer", () => {
    assert.equal(productSource("", origin), "direct");
    assert.equal(productSource("https://other.example/products?search=lamp", origin), "direct");
    assert.equal(productSource(`${origin}/cart`, origin), "direct");
    assert.equal(productSource("not a url", origin), "direct");
  });
});

describe("tracker", () => {
  test("waits, then sends everything queued in one request", async () => {
    const sent = [];
    const timers = manualTimers();
    const tracker = createTracker({ send: async (batch) => sent.push(batch), session: "s-1234567", ...timers });

    tracker.track("product_view", { product_id: "p1", source: "direct" });
    tracker.track("product_view", { product_id: "p2", source: "direct" });
    assert.deepEqual(sent, []);

    await timers.fire();

    assert.equal(sent.length, 1);
    assert.deepEqual(sent[0].map((e) => e.product_id), ["p1", "p2"]);
    assert.equal(tracker.pending(), 0);
  });

  test("sends at most 100 events per request and keeps the rest for the next", async () => {
    const sent = [];
    const timers = manualTimers();
    const tracker = createTracker({ send: async (batch) => sent.push(batch.length), session: "s-1234567", ...timers });
    for (let i = 0; i < 130; i += 1) tracker.track("product_view", { product_id: `p${i}`, source: "direct" });

    await tracker.flush();
    await tracker.flush();

    assert.deepEqual(sent, [100, 30]);
  });

  test("a network failure keeps the events, and the resend uses the same ids", async () => {
    const attempts = [];
    let fail = true;
    const timers = manualTimers();
    const tracker = createTracker({
      send: async (batch) => {
        attempts.push(batch.map((e) => e.event_id));
        if (fail) throw new TypeError("network down");
      },
      session: "s-1234567",
      ...timers,
    });
    tracker.track("search", { query: "lamp", result_count: 1 });

    await tracker.flush();
    fail = false;
    await tracker.flush();

    assert.equal(attempts.length, 2);
    assert.deepEqual(attempts[0], attempts[1]);
    assert.equal(tracker.pending(), 0);
  });

  test("a server error or 429 is retried, a 4xx for a bad event is dropped", async () => {
    const attempts = [];
    const replies = [httpError(500), httpError(429), httpError(422), null];
    const tracker = createTracker({
      send: async (batch) => {
        attempts.push(batch[0].product_id);
        const reply = replies.shift();
        if (reply) throw reply;
      },
      session: "s-1234567",
      ...manualTimers(),
    });
    tracker.track("product_view", { product_id: "bad", source: "direct" });

    await tracker.flush();
    await tracker.flush();
    await tracker.flush();
    assert.deepEqual(attempts, ["bad", "bad", "bad"]);
    assert.equal(tracker.pending(), 0);

    tracker.track("product_view", { product_id: "good", source: "direct" });
    await tracker.flush();
    assert.equal(attempts.at(-1), "good");
  });

  test("while sending keeps failing, the oldest events are dropped first", async () => {
    const tracker = createTracker({
      send: async () => {
        throw new TypeError("down");
      },
      session: "s-1234567",
      ...manualTimers(),
    });
    for (let i = 0; i < 520; i += 1) tracker.track("product_view", { product_id: `p${i}`, source: "direct" });

    await tracker.flush();

    assert.equal(tracker.pending(), 500);
  });

  test("events are stamped with the time they happened, not when they were sent", async () => {
    const sent = [];
    const times = [new Date("2026-11-18T12:00:00Z"), new Date("2026-11-18T12:00:09Z")];
    const tracker = createTracker({
      send: async (batch) => sent.push(...batch),
      session: "s-1234567",
      now: () => times.shift(),
      ...manualTimers(),
    });
    tracker.track("search", { query: "a", result_count: 0 });
    tracker.track("search", { query: "b", result_count: 0 });

    await tracker.flush();

    assert.deepEqual(sent.map((e) => e.occurred_at), ["2026-11-18T12:00:00.000Z", "2026-11-18T12:00:09.000Z"]);
  });
});
