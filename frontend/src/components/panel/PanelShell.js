"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import RequireSignIn from "@/components/RequireSignIn";
import { useSession } from "@/lib/session";

const icons = {
  dashboard: "M3 13h8V3H3zM13 21h8V11h-8zM3 21h8v-6H3zM13 3v6h8V3z",
  products: "M20 7l-8-4-8 4 8 4 8-4zM4 7v10l8 4 8-4V7",
  add: "M12 5v14M5 12h14",
  sales: "M4 19V9M10 19V5M16 19v-7M22 19H2",
  orders: "M6 2l1.5 4h9L18 2M3 6h18l-2 14H5z",
  categories: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
};

const MENUS = {
  seller: {
    title: (user) => `${user.first_name}'s shop`,
    items: [
      ["/seller", "Dashboard", "dashboard"],
      ["/seller/products", "My products", "products"],
      ["/seller/products/new", "Add a product", "add"],
      ["/seller/sales", "Sales", "sales"],
    ],
  },
  admin: {
    title: () => "Shopverse admin",
    items: [
      ["/admin/orders", "Orders", "orders"],
      ["/admin/categories", "Categories", "categories"],
      ["/admin/products", "All products", "products"],
    ],
  },
};

function isActive(pathname, href) {
  // "/seller" only matches itself; deeper links match their section ("/seller/products/abc").
  if (href === "/seller") return pathname === "/seller";
  if (href === "/seller/products") return pathname.startsWith("/seller/products") && pathname !== "/seller/products/new";
  return pathname === href || pathname.startsWith(`${href}/`);
}

function Sidebar({ role, user }) {
  const pathname = usePathname();
  const menu = MENUS[role];
  return (
    <aside className="raised h-fit p-4 md:sticky md:top-6">
      <div className="px-2.5 pb-4 pt-1.5">
        <p className="font-display text-lg font-extrabold">{menu.title(user)}</p>
        <p className="truncate text-sm text-ink-soft">{user.email}</p>
        <span className="mt-2 inline-block rounded-full px-2.5 py-0.5 text-xs font-bold capitalize text-accent shadow-[inset_0_0_0_2px_var(--accent)]">
          {role}
        </span>
      </div>
      <nav aria-label={`${role} menu`} className="flex gap-2 overflow-x-auto md:block md:space-y-1.5">
        {menu.items.map(([href, label, icon]) => {
          const active = isActive(pathname, href);
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={`flex shrink-0 items-center gap-2.5 rounded-xl px-3 py-2.5 font-semibold ${
                active ? "pressed" : "text-ink-soft hover:text-accent"
              }`}
            >
              <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d={icons[icon]} />
              </svg>
              {label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}

function RoleGate({ role, children }) {
  const { user } = useSession();
  if (user.role !== role) {
    return (
      <div className="raised mx-auto max-w-lg px-8 py-14 text-center">
        <h1 className="text-3xl font-extrabold">This area is for {role}s</h1>
        <p className="mt-3 text-ink-soft">
          You&apos;re signed in as {user.email}, which is a {user.role} account.
          {role === "seller" ? " Create a new account and tick “I want to sell on Shopverse” to open a shop." : ""}
        </p>
        <Link href="/" className="btn btn-metal mt-7">Back to the shop</Link>
      </div>
    );
  }
  return (
    <div className="grid gap-8 md:grid-cols-[230px_1fr]">
      <Sidebar role={role} user={user} />
      <div className="min-w-0">{children}</div>
    </div>
  );
}

// Every seller and admin page is wrapped in this: sign-in check, role check, sidebar.
export default function PanelShell({ role, children }) {
  return (
    <RequireSignIn>
      <RoleGate role={role}>{children}</RoleGate>
    </RequireSignIn>
  );
}

export function PageTitle({ title, lede, actions }) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-4xl font-extrabold sm:text-5xl">{title}</h1>
        {lede && <p className="mt-2 text-ink-soft">{lede}</p>}
      </div>
      {actions}
    </div>
  );
}

const PRODUCT_STATUS = {
  active: ["Published", "text-accent shadow-[inset_0_0_0_2px_var(--accent)]"],
  draft: ["Draft", "text-ink-soft shadow-[inset_0_0_0_2px_var(--line)]"],
  archived: ["Archived", "text-ink-soft line-through"],
};

export function ProductStatus({ status }) {
  const [label, style] = PRODUCT_STATUS[status] || [status, ""];
  return <span className={`inline-block rounded-full px-3 py-0.5 text-sm font-semibold ${style}`}>{label}</span>;
}
