"use client";

import PanelShell, { PageTitle } from "@/components/panel/PanelShell";
import ProductList from "@/components/panel/ProductList";

export default function AdminProductsPage() {
  return (
    <PanelShell role="admin">
      <PageTitle title="All products" lede="Every seller's products, drafts included. Archive anything that breaks the rules." />
      <ProductList editBase="/admin/products" showSeller />
    </PanelShell>
  );
}
