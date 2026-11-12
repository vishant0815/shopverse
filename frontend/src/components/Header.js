"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { useSession } from "@/lib/session";

import SearchBox from "./SearchBox";
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

        <SearchBox />

        <nav className="ml-auto flex items-center gap-5 text-sm font-medium" aria-label="Account">
          {ready && user ? (
            <>
              {user.role === "seller" && <Link href="/seller" className="font-semibold text-accent hover:underline">Your shop</Link>}
              {user.role === "admin" && <Link href="/admin/orders" className="font-semibold text-accent hover:underline">Admin</Link>}
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
