import Link from "next/link";

export default function NotFound() {
  return (
    <div className="raised mx-auto max-w-lg px-8 py-16 text-center">
      <p className="metal-text font-display text-7xl font-extrabold">404</p>
      <h1 className="mt-4 text-4xl font-extrabold">This page isn&apos;t on the shelf</h1>
      <p className="mt-3 text-ink-soft">The link may be old, or the product may no longer be sold.</p>
      <Link href="/products" className="btn btn-metal mt-8">Browse all products</Link>
    </div>
  );
}
