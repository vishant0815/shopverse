"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { useSession } from "@/lib/session";

export default function Header() {
  const { user, ready, cartCount, logout } = useSession();
  const router = useRouter();
  const pathname = usePathname();

  return (
    <header className="border-b border-line bg-white">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-4">
        <Link href="/" className="font-display text-2xl font-extrabold tracking-tight">
          shopverse
        </Link>

        <form action="/products" className="order-last flex w-full sm:order-none sm:w-auto sm:flex-1" role="search">
          <label htmlFor="site-search" className="sr-only">Search products</label>
          <input
            id="site-search"
            name="search"
            type="search"
            placeholder="Search phones, shirts, desks…"
            className="w-full rounded-l-sm border border-r-0 border-ink px-3 py-2"
          />
          <button className="rounded-r-sm bg-ink px-4 font-semibold text-white hover:bg-cobalt">Search</button>
        </form>

        <nav className="ml-auto flex items-center gap-5 text-sm font-medium" aria-label="Account">
          {ready && user ? (
            <>
              <Link href="/orders" className="hover:text-cobalt">Orders</Link>
              <Link href="/account" className="hover:text-cobalt">{user.first_name}</Link>
              <button
                className="hover:text-cobalt"
                onClick={async () => {
                  await logout();
                  router.push("/");
                }}
              >
                Sign out
              </button>
            </>
          ) : ready ? (
            <Link href={`/login?next=${encodeURIComponent(pathname)}`} className="hover:text-cobalt">Sign in</Link>
          ) : null}
          <Link href="/cart" className="flex items-center gap-2 hover:text-cobalt">
            Basket
            <span
              className="min-w-6 rounded-full bg-sticker px-1.5 text-center font-display font-bold"
              aria-label={`${cartCount} items in basket`}
            >
              {cartCount}
            </span>
          </Link>
        </nav>
      </div>
    </header>
  );
}
