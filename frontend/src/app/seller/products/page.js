"use client";

import Link from "next/link";

import PanelShell, { PageTitle } from "@/components/panel/PanelShell";
import ProductList from "@/components/panel/ProductList";

export default function SellerProductsPage() {
  return (
    <PanelShell role="seller">
      <PageTitle
        title="My products"
        lede="Drafts are only visible to you. Archived products stay on past orders."
        actions={<Link href="/seller/products/new" className="btn btn-metal">+ Add a product</Link>}
      />
      <ProductList editBase="/seller/products" />
    </PanelShell>
  );
}
