"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import RequireSignIn from "@/components/RequireSignIn";
import StatusBadge from "@/components/StatusBadge";
import { api } from "@/lib/api";
import { date, money } from "@/lib/format";

function OrderList() {
  const [orders, setOrders] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/api/v1/orders/").then((data) => setOrders(data.results)).catch((err) => setError(err.message));
  }, []);

  if (!orders) return <p className="py-24 text-center text-ink-soft">{error || "Loading your orders…"}</p>;

  return (
    <div>
      <h1 className="mb-6 text-4xl font-extrabold">Your orders</h1>
      {orders.length === 0 ? (
        <div className="py-12">
          <p className="text-lg">You haven&apos;t ordered anything yet.</p>
          <Link href="/products" className="mt-3 inline-block font-medium text-cobalt hover:underline">Start shopping</Link>
        </div>
      ) : (
        <table className="w-full border-y border-line text-left">
          <thead className="text-sm text-ink-soft">
            <tr>
              <th scope="col" className="py-3 font-medium">Order</th>
              <th scope="col" className="py-3 font-medium">Placed</th>
              <th scope="col" className="hidden py-3 font-medium sm:table-cell">Items</th>
              <th scope="col" className="py-3 font-medium">Status</th>
              <th scope="col" className="py-3 text-right font-medium">Total</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {orders.map((order) => (
              <tr key={order.id}>
                <td className="py-4">
                  <Link href={`/orders/${order.number}`} className="font-semibold text-cobalt hover:underline">{order.number}</Link>
                </td>
                <td className="py-4">{date(order.created_at)}</td>
                <td className="hidden py-4 sm:table-cell">{order.item_count}</td>
                <td className="py-4"><StatusBadge status={order.status} /></td>
                <td className="py-4 text-right font-semibold">{money(order.total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default function OrdersPage() {
  return (
    <RequireSignIn>
      <OrderList />
    </RequireSignIn>
  );
}
