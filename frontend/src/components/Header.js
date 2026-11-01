"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { useSession } from "@/lib/session";

import ThemeSwitch from "./ThemeSwitch";

export default function Header() {
  const { user, ready, cartCount, logout } = useSession();
  const router = useRouter();
  const pathname = usePathname();

  return (
    <header>
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-4 px-4 py-5 sm:px-6">
        <Link href="/" className="font-display text-[1.75rem] font-extrabold tracking-tight">
          shop<span className="metal-text">verse</span>
        </Link>

        <form action="/products" role="search" className="inset order-last flex w-full items-center gap-2 py-1.5 pl-4 pr-1.5 sm:order-none sm:w-auto sm:flex-1">
          <label htmlFor="site-search" className="sr-only">Search products</label>
          <input
            id="site-search"
            name="search"
            type="search"
            placeholder="Search phones, shirts, desks…"
            className="min-w-0 flex-1 bg-transparent py-1.5 outline-none placeholder:text-ink-soft"
          />
          <button className="btn btn-metal px-4 py-2 text-sm">Search</button>
        </form>

        <nav className="ml-auto flex items-center gap-5 text-sm font-medium" aria-label="Account">
          {ready && user ? (
            <>
              <Link href="/orders" className="hover:text-accent">Orders</Link>
              <Link href="/account" className="hover:text-accent">{user.first_name}</Link>
              <button
                className="hover:text-accent"
                onClick={async () => {
                  await logout();
                  router.push("/");
                }}
              >
                Sign out
              </button>
            </>
          ) : ready ? (
            <Link href={`/login?next=${encodeURIComponent(pathname)}`} className="hover:text-accent">Sign in</Link>
          ) : null}
          <Link href="/cart" className="flex items-center gap-2 hover:text-accent">
            Basket
            {/* key changes with the count, so the pulse animation replays whenever it changes */}
            <span
              key={cartCount}
              className={`count-badge ${cartCount > 0 ? "bump" : "count-badge-empty"}`}
              aria-label={`${cartCount} items in basket`}
            >
              {cartCount}
            </span>
          </Link>
          <ThemeSwitch />
        </nav>
      </div>
    </header>
  );
}
