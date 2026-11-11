import StatusBadge from "@/components/StatusBadge";
import { money, variantLabel } from "@/lib/format";

// The seller's own order lines. "compact" shortens order numbers and drops the date column.
export default function SalesTable({ sales, compact = false }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left">
        <thead className="text-sm text-ink-soft">
          <tr>
            <th scope="col" className="px-2.5 py-2 font-medium">Order</th>
            {!compact && <th scope="col" className="px-2.5 py-2 font-medium">Date</th>}
            <th scope="col" className="px-2.5 py-2 font-medium">Product</th>
            <th scope="col" className="px-2.5 py-2 font-medium">Qty</th>
            <th scope="col" className="px-2.5 py-2 font-medium">Status</th>
            <th scope="col" className="px-2.5 py-2 text-right font-medium">Amount</th>
          </tr>
        </thead>
        <tbody>
          {sales.map((sale, index) => (
            <tr key={`${sale.order_number}-${sale.sku}-${index}`} className="border-t border-line">
              <td className="whitespace-nowrap px-2.5 py-3 text-sm">
                {compact ? `SV-…${sale.order_number.slice(-6)}` : sale.order_number}
              </td>
              {!compact && (
                <td className="whitespace-nowrap px-2.5 py-3 text-sm">
                  {new Date(sale.ordered_at).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}
                </td>
              )}
              <td className="px-2.5 py-3">
                {sale.product_name}
                <span className="block text-xs text-ink-soft">{variantLabel(sale)}</span>
              </td>
              <td className="px-2.5 py-3">{sale.quantity}</td>
              <td className="whitespace-nowrap px-2.5 py-3"><StatusBadge status={sale.order_status} /></td>
              <td className="whitespace-nowrap px-2.5 py-3 text-right font-display text-base font-extrabold">
                <span className="metal-text">{money(sale.line_total)}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
