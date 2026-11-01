import Link from "next/link";
import { notFound } from "next/navigation";

import AddToBasket from "@/components/AddToBasket";
import CatalogueUnavailable from "@/components/CatalogueUnavailable";
import { CatalogueDown, getProduct } from "@/lib/catalog-server";

export async function generateMetadata({ params }) {
  const { slug } = await params;
  try {
    const product = await getProduct(slug);
    return product ? { title: product.name, description: product.description } : {};
  } catch {
    return {};
  }
}

export default async function ProductPage({ params }) {
  const { slug } = await params;
  let product;
  try {
    product = await getProduct(slug);
  } catch (error) {
    if (error instanceof CatalogueDown) return <CatalogueUnavailable />;
    throw error;
  }
  if (!product) notFound();

  const [mainImage, ...moreImages] = product.images;

  return (
    <div>
      <nav aria-label="Breadcrumb" className="mb-6 text-sm text-ink-soft">
        <Link href="/products" className="hover:text-accent">All products</Link>
        <span aria-hidden="true"> / </span>
        <Link href={`/products?category=${product.category.slug}`} className="hover:text-accent">{product.category.name}</Link>
      </nav>

      <div className="grid gap-12 md:grid-cols-2">
        <div className="space-y-5 self-start">
          <div className="raised p-4">
            <div className="inset aspect-square overflow-hidden">
              {mainImage && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={mainImage.url} alt={mainImage.alt_text || product.name} className="photo h-full w-full object-cover" />
              )}
            </div>
          </div>
          {moreImages.length > 0 && (
            <div className="grid grid-cols-4 gap-4">
              {moreImages.map((image) => (
                <div key={image.id} className="raised-sm overflow-hidden p-1.5">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={image.url} alt={image.alt_text || ""} className="photo aspect-square rounded-lg object-cover" />
                </div>
              ))}
            </div>
          )}
        </div>

        <div>
          {product.brand && <p className="text-ink-soft">{product.brand}</p>}
          <h1 className="mt-1 text-4xl font-extrabold sm:text-5xl">{product.name}</h1>
          <AddToBasket variants={product.variants} />
          {product.description && (
            <div className="mt-10">
              <h2 className="text-xl font-bold">About this product</h2>
              <p className="mt-2 max-w-prose leading-relaxed text-ink-soft">{product.description}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
