// Seller shops: what each approval status means to the seller and to an admin.
// Pure helpers with no network, so `npm test` can run them directly.

const COPY = {
  pending: {
    label: "Waiting for approval",
    note: "Your shop is waiting for an admin to approve it. You can set it up now, but you can't add or change products until it's approved.",
  },
  approved: {
    label: "Approved",
    note: "Your shop is approved. You can add and change products.",
  },
  suspended: {
    label: "Suspended",
    note: "Your shop is suspended. Shoppers can't see your products, and you can't change them until an admin reinstates the shop. You can still read them here.",
  },
};

export const ADMIN_TABS = [
  ["", "All"],
  ["pending", "Pending"],
  ["approved", "Approved"],
  ["suspended", "Suspended"],
];

export function shopStatusLabel(status) {
  return COPY[status]?.label ?? status;
}

export function shopStatusNote(status) {
  return COPY[status]?.note ?? "";
}

export function canChangeProducts(status) {
  return status === "approved";
}

// The admin's actions for a shop, from its status. Approving a suspended shop reinstates it.
export function adminActions(status) {
  if (status === "pending") return [{ action: "approve", label: "Approve" }];
  if (status === "approved") return [{ action: "suspend", label: "Suspend" }];
  if (status === "suspended") return [{ action: "approve", label: "Reinstate" }];
  return [];
}

// The admin list for one tab. An empty status means every shop.
export function sellersQuery(status) {
  return status ? `/api/v1/admin/sellers/?status=${encodeURIComponent(status)}` : "/api/v1/admin/sellers/";
}

// Suspending hides a shop's products from shoppers, so the admin confirms first.
export function confirmSuspend(shopName) {
  return `Suspend “${shopName}”? Shoppers won't see its products until you reinstate the shop.`;
}
