// What an admin can do next with an order. "Paid" is left out on purpose:
// only the payments service marks orders as paid, once the money has arrived.
export const NEXT_STEPS = {
  paid: [
    { status: "shipped", label: "Mark shipped", variant: "primary" },
    { status: "cancelled", label: "Cancel", variant: "danger" },
  ],
  shipped: [{ status: "delivered", label: "Mark delivered", variant: "primary" }],
  pending_payment: [{ status: "cancelled", label: "Cancel", variant: "danger" }],
};

export function confirmMessage(order, step) {
  if (step.status !== "cancelled") return null;
  if (order.status === "paid") {
    return `Cancel order ${order.number}? The customer has already paid. Refunds aren't automatic yet, so you'll need to refund them from the Stripe dashboard.`;
  }
  return `Cancel order ${order.number}? The customer hasn't paid yet.`;
}
