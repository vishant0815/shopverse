"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { useSession } from "@/lib/session";

import { Button, Field, Notice } from "./ui";

// Only follow "next" links that stay on this site, so a crafted link can't
// send someone to another website after they sign in.
function safeNext(value) {
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/";
}

export default function AuthForm({ mode }) {
  const isRegister = mode === "register";
  const { login, register } = useSession();
  const router = useRouter();
  const next = safeNext(useSearchParams().get("next"));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState({});

  async function submit(event) {
    event.preventDefault();
    const form = Object.fromEntries(new FormData(event.currentTarget));
    setBusy(true);
    setError("");
    setFieldErrors({});
    try {
      if (isRegister) {
        await register({
          email: form.email,
          password: form.password,
          first_name: form.first_name,
          last_name: form.last_name,
          role: form.seller ? "seller" : "customer",
        });
      } else {
        await login(form.email, form.password);
      }
      router.push(next);
    } catch (err) {
      if (err.status === 400 && err.data && typeof err.data === "object" && !err.data.detail) {
        const perField = Object.fromEntries(
          Object.entries(err.data).map(([key, value]) => [key, Array.isArray(value) ? value.join(" ") : String(value)]),
        );
        setFieldErrors(perField);
        setError(perField.non_field_errors || (Object.keys(perField).length ? "" : err.message));
      } else {
        setError(err.status === 429 ? "Too many attempts. Wait a minute and try again." : err.message);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-md py-8">
      <h1 className="text-4xl font-extrabold">{isRegister ? "Create an account" : "Sign in"}</h1>
      <p className="mt-2 text-ink-soft">
        {isRegister ? "Already have one? " : "New to Shopverse? "}
        <Link href={`/${isRegister ? "login" : "register"}?next=${encodeURIComponent(next)}`} className="font-medium text-cobalt hover:underline">
          {isRegister ? "Sign in" : "Create an account"}
        </Link>
      </p>

      <form onSubmit={submit} className="mt-8 space-y-4" noValidate>
        <Notice>{error}</Notice>
        {isRegister && (
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="First name" name="first_name" autoComplete="given-name" required error={fieldErrors.first_name} />
            <Field label="Last name" name="last_name" autoComplete="family-name" error={fieldErrors.last_name} />
          </div>
        )}
        <Field label="Email" name="email" type="email" autoComplete="email" required error={fieldErrors.email} />
        <Field
          label="Password"
          name="password"
          type="password"
          autoComplete={isRegister ? "new-password" : "current-password"}
          required
          hint={isRegister ? "At least 8 characters, not just numbers, and not a common password." : undefined}
          error={fieldErrors.password}
        />
        {isRegister && (
          <label className="flex items-start gap-3 text-sm">
            <input type="checkbox" name="seller" className="mt-0.5 h-4 w-4 accent-cobalt" />
            <span>I want to sell on Shopverse</span>
          </label>
        )}
        <Button type="submit" busy={busy} className="w-full py-3">
          {busy ? "Please wait…" : isRegister ? "Create account" : "Sign in"}
        </Button>
      </form>
    </div>
  );
}
