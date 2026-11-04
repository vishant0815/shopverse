"use client";

import { useParams } from "next/navigation";

import PanelShell, { PageTitle } from "@/components/panel/PanelShell";
import ProductEditor from "@/components/panel/ProductEditor";

export default function AdminEditProductPage() {
  const { id } = useParams();
  return (
    <PanelShell role="admin">
      <PageTitle title="Edit product" lede="You're editing another seller's listing as an admin." />
      <ProductEditor productId={id} listHref="/admin/products" />
    </PanelShell>
  );
}
