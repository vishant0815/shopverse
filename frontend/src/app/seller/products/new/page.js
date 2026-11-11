"use client";

import PanelShell, { PageTitle } from "@/components/panel/PanelShell";
import ProductEditor from "@/components/panel/ProductEditor";

export default function NewProductPage() {
  return (
    <PanelShell role="seller">
      <PageTitle title="Add a product" lede="Save it as a draft first if you're not ready for customers to see it." />
      <ProductEditor listHref="/seller/products" />
    </PanelShell>
  );
}
