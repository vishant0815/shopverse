import { orderStatus } from "@/lib/format";

// Awaiting payment is the one status that needs the customer to act, so it gets the red accent.
const STYLES = {
  reserving: "text-ink-soft shadow-[inset_0_0_0_2px_var(--line)]",
  pending_payment: "text-power shadow-[inset_0_0_0_2px_var(--power)]",
  paid: "text-accent shadow-[inset_0_0_0_2px_var(--accent)]",
  shipped: "text-accent shadow-[inset_0_0_0_2px_var(--accent)]",
  delivered: "btn-metal",
  cancelled: "text-ink-soft line-through",
};

export default function StatusBadge({ status }) {
  return (
    <span className={`inline-block rounded-full px-3 py-1 text-sm font-semibold ${STYLES[status] || ""}`}>
      {orderStatus(status)}
    </span>
  );
}
