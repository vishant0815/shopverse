"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { useSession } from "@/lib/session";

// Wraps pages that only make sense signed in (basket, checkout, orders, account).
export default function RequireSignIn({ children }) {
  const { user, ready } = useSession();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (ready && !user) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [ready, user, router, pathname]);

  if (!ready || !user) {
    return <p className="py-24 text-center text-ink-soft">Loading…</p>;
  }
  return children;
}
