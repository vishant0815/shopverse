"use client";

import { Elements, PaymentElement, useElements, useStripe } from "@stripe/react-stripe-js";
import { loadStripe } from "@stripe/stripe-js";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { money } from "@/lib/format";

import { Button, Notice } from "./ui";

const publishableKey = process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY;
const stripePromise = publishableKey ? loadStripe(publishableKey) : null;

// After Stripe accepts the card, the order becomes "paid" only once Stripe's webhook
// reaches the payments service. Check the order a few times until that happens.
async function waitUntilPaid(number, attempts = 15) {
  for (let i = 0; i < attempts; i += 1) {
    const order = await api(`/api/v1/orders/${encodeURIComponent(number)}/`);
    if (order.status !== "pending_payment") return true;
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
  return false;
}

export default function PaymentPanel({ order, onPaid }) {
  const [provider, setProvider] = useState(null);
  const [payment, setPayment] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const health = await api("/api/payments-health", { auth: false });
        setProvider(health.provider);
        setPayment(await api("/api/v1/payments", { method: "POST", body: { order_number: order.number } }));
      } catch (err) {
        setError(err.code === "already_paid" ? "" : err.message);
        if (err.code === "already_paid") onPaid();
      }
    })();
  }, [order.number, onPaid]);

  return (
    <section aria-labelledby="pay-heading" className="border-2 border-ink bg-white p-6">
      <h2 id="pay-heading" className="text-2xl font-bold">Pay {money(order.total)}</h2>
      <div className="mt-4 space-y-4">
        <Notice>{error}</Notice>
        {!payment && !error && <p className="text-ink-soft">Getting your payment ready…</p>}
        {payment?.last_error && <Notice>{payment.last_error} Try again.</Notice>}
        {payment && provider === "fake" && (
          <FakePayment order={order} onDone={onPaid} onError={setError} onFailed={setPayment} />
        )}
        {payment && provider === "stripe" && (
          stripePromise ? (
            <Elements stripe={stripePromise} options={{ clientSecret: payment.client_secret }}>
              <StripePayment order={order} onDone={onPaid} onError={setError} />
            </Elements>
          ) : (
            <Notice>Stripe is enabled on the server, but NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY isn&apos;t set for the storefront.</Notice>
          )
        )}
      </div>
    </section>
  );
}

function FakePayment({ order, onDone, onError, onFailed }) {
  const [busy, setBusy] = useState(null);

  async function simulate(outcome) {
    setBusy(outcome);
    onError("");
    try {
      const result = await api(`/api/v1/payments/${encodeURIComponent(order.number)}/simulate`, {
        method: "POST",
        body: { outcome },
      });
      if (result.payment.status === "succeeded") onDone();
      else onFailed(result.payment);
    } catch (err) {
      onError(err.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-ink-soft">
        This store runs in test mode, so there&apos;s no card form. Choose what the card does:
      </p>
      <div className="flex flex-wrap gap-3">
        <Button onClick={() => simulate("succeeded")} busy={busy === "succeeded"} disabled={!!busy}>
          {busy === "succeeded" ? "Paying…" : "Pay with a test card"}
        </Button>
        <Button variant="secondary" onClick={() => simulate("failed")} busy={busy === "failed"} disabled={!!busy}>
          Try a declined card
        </Button>
      </div>
    </div>
  );
}

function StripePayment({ order, onDone, onError }) {
  const stripe = useStripe();
  const elements = useElements();
  const [busy, setBusy] = useState(false);

  async function pay(event) {
    event.preventDefault();
    if (!stripe || !elements) return;
    setBusy(true);
    onError("");
    // Card details go straight from this form to Stripe; Shopverse never sees them.
    const { error } = await stripe.confirmPayment({
      elements,
      redirect: "if_required",
      confirmParams: { return_url: `${window.location.origin}/orders/${order.number}` },
    });
    if (error) {
      onError(error.message);
      setBusy(false);
      return;
    }
    if (await waitUntilPaid(order.number)) onDone();
    else onError("Payment received. Your order will show as paid in a moment; refresh this page.");
    setBusy(false);
  }

  return (
    <form onSubmit={pay} className="space-y-4">
      <PaymentElement />
      <p className="text-sm text-ink-soft">Test card: 4242 4242 4242 4242, any future date, any CVC.</p>
      <Button type="submit" busy={busy} disabled={!stripe} className="py-3">
        {busy ? "Paying…" : `Pay ${money(order.total)}`}
      </Button>
    </form>
  );
}
