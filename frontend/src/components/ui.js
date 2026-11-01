"use client";

// Small building blocks shared by forms across the site.

export function Button({ variant = "primary", className = "", busy = false, children, ...props }) {
  const styles = {
    primary: "btn-metal",
    secondary: "btn-soft",
    danger: "btn-power",
    quiet: "text-accent underline-offset-4 hover:underline",
  };
  const base = variant === "quiet" ? "inline-flex items-center gap-2 font-semibold" : "btn";
  return (
    <button
      className={`${base} ${styles[variant]} ${className}`}
      disabled={busy || props.disabled}
      aria-busy={busy || undefined}
      {...props}
    >
      {children}
    </button>
  );
}

export function Field({ label, error, hint, id, className = "", ...props }) {
  const inputId = id || props.name;
  return (
    <label htmlFor={inputId} className={`block ${className}`}>
      <span className="mb-1.5 block text-sm font-medium">{label}</span>
      <input
        id={inputId}
        className="field"
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${inputId}-error` : undefined}
        {...props}
      />
      {hint && !error && <span className="mt-1.5 block text-sm text-ink-soft">{hint}</span>}
      {error && (
        <span id={`${inputId}-error`} className="mt-1.5 block text-sm font-medium text-power">
          {error}
        </span>
      )}
    </label>
  );
}

export function Notice({ tone = "error", children }) {
  if (!children) return null;
  const tones = {
    error: "text-power",
    success: "text-accent",
    info: "text-ink",
  };
  const dot = { error: "bg-power", success: "bg-accent", info: "bg-ink-soft" };
  return (
    <div role={tone === "error" ? "alert" : "status"} className={`inset flex items-start gap-3 px-4 py-3 ${tones[tone]}`}>
      <span aria-hidden="true" className={`mt-2 h-2 w-2 shrink-0 rounded-full ${dot[tone]}`} />
      <div>{children}</div>
    </div>
  );
}
