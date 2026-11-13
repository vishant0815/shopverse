"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { SORT_OPTIONS } from "@/lib/search-model";

export default function SortSelect({ value }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  return (
    <label className="flex items-center gap-3 text-sm">
      <span className="font-medium">Sort by</span>
      <select
        value={value}
        onChange={(event) => {
          const params = new URLSearchParams(searchParams);
          params.set("sort", event.target.value);
          params.delete("page");
          router.push(`${pathname}?${params}`);
        }}
        className="field w-auto py-2 pr-8"
      >
        {SORT_OPTIONS.map(([key, label]) => (
          <option key={key} value={key}>{label}</option>
        ))}
      </select>
    </label>
  );
}
