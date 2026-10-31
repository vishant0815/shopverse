import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-lg py-24 text-center">
      <span className="price-tag text-2xl">404</span>
      <h1 className="mt-6 text-4xl font-extrabold">This page isn&apos;t on the shelf</h1>
      <p className="mt-3 text-ink-soft">The link may be old, or the product may no longer be sold.</p>
      <Link href="/products" className="mt-6 inline-block font-medium text-cobalt hover:underline">Browse all products</Link>
    </div>
  );
}
