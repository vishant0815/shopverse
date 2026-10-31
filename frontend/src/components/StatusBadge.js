import { orderStatus } from "@/lib/format";

const STYLES = {
  pending_payment: "bg-sticker text-ink",
  paid: "bg-cobalt text-white",
  shipped: "bg-ink text-white",
  delivered: "bg-ok text-white",
  cancelled: "bg-shelf text-ink-soft line-through",
};

export default function StatusBadge({ status }) {
  return (
    <span className={`inline-block rounded-sm px-2 py-0.5 text-sm font-semibold ${STYLES[status] || "bg-shelf"}`}>
      {orderStatus(status)}
    </span>
  );
}
