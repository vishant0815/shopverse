"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { canChangeProducts, shopStatusLabel, shopStatusNote } from "@/lib/seller";

// Shown above every seller page until the shop is approved, so a seller knows
// why they can't change products. Quietly shows nothing if the status can't be loaded.
export default function ShopStatusBanner() {
  const [status, setStatus] = useState(null);

  useEffect(() => {
    api("/api/v1/sellers/me/")
      .then((shop) => setStatus(shop.status))
      .catch(() => setStatus(null));
  }, []);

  if (!status || canChangeProducts(status)) return null;

  return (
    <div className="mb-6">
      <Notice tone={status === "suspended" ? "error" : "info"}>
        <p className="font-semibold">{shopStatusLabel(status)}</p>
        <p className="mt-1 text-ink-soft">
          {shopStatusNote(status)}{" "}
          <Link href="/seller/shop" className="font-semibold text-accent hover:underline">
            Open My shop
          </Link>
        </p>
      </Notice>
    </div>
  );
}
