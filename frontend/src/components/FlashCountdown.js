"use client";

import { useEffect, useState } from "react";

import { countdown } from "@/lib/flashSale";

// "Flash sale · ends in 02:14:37", counting down once a second. It renders nothing until the
// page has loaded in the browser, so the server and the first paint agree.
export default function FlashCountdown({ endsAt }) {
  const [now, setNow] = useState(null);

  useEffect(() => {
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  if (now === null) return null;
  const remaining = new Date(endsAt).getTime() - now;
  if (remaining <= 0) {
    return <span className="inline-block rounded-full px-3.5 py-1 text-sm font-semibold text-ink-soft shadow-[inset_0_0_0_2px_var(--line)]">Flash sale ended</span>;
  }
  return (
    <span className="inline-block rounded-full px-3.5 py-1 text-sm font-semibold text-accent shadow-[inset_0_0_0_2px_var(--accent)]">
      Flash sale · ends in <time dateTime={endsAt}>{countdown(remaining)}</time>
    </span>
  );
}
