"use client";

import { useParams } from "next/navigation";

import PanelShell, { PageTitle } from "@/components/panel/PanelShell";
import ProductEditor from "@/components/panel/ProductEditor";

export default function EditProductPage() {
  const { id } = useParams();
  return (
    <PanelShell role="seller">
      <PageTitle title="Edit product" />
      <ProductEditor productId={id} listHref="/seller/products" />
    </PanelShell>
  );
}
