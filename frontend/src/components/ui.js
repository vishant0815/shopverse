"use client";

// Small building blocks shared by forms across the site.

export function Button({ variant = "primary", className = "", busy = false, children, ...props }) {
  const styles = {
    primary: "bg-cobalt text-white hover:bg-cobalt-deep disabled:bg-ink-soft",
    secondary: "border border-ink text-ink hover:bg-ink hover:text-white disabled:opacity-50",
    quiet: "text-cobalt underline-offset-4 hover:underline disabled:opacity-50",
    danger: "border border-sale text-sale hover:bg-sale hover:text-white disabled:opacity-50",
  };
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-sm px-5 py-2.5 font-semibold transition-colors disabled:cursor-not-allowed ${styles[variant]} ${className}`}
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
      <span className="mb-1 block text-sm font-medium">{label}</span>
      <input
        id={inputId}
        className={`w-full rounded-sm border bg-white px-3 py-2 ${error ? "border-sale" : "border-line"} focus:border-cobalt`}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${inputId}-error` : undefined}
        {...props}
      />
      {hint && !error && <span className="mt-1 block text-sm text-ink-soft">{hint}</span>}
      {error && (
        <span id={`${inputId}-error`} className="mt-1 block text-sm text-sale">
          {error}
        </span>
      )}
    </label>
  );
}

export function Notice({ tone = "error", children }) {
  if (!children) return null;
  const tones = {
    error: "border-sale bg-sale/5 text-sale",
    success: "border-ok bg-ok/5 text-ok",
    info: "border-line bg-white text-ink",
  };
  return (
    <div role={tone === "error" ? "alert" : "status"} className={`border-l-4 px-4 py-3 ${tones[tone]}`}>
      {children}
    </div>
  );
}
