import "./globals.css";

import Header from "@/components/Header";
import { SessionProvider } from "@/lib/session";

export const metadata = {
  title: { default: "Shopverse", template: "%s | Shopverse" },
  description: "Phones, clothes and home goods from independent sellers, paid for in one checkout.",
  icons: { icon: "/favicon.svg" },
};

export const viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#1a1d1f" },
    { media: "(prefers-color-scheme: light)", color: "#e3e8e5" },
  ],
};

// Runs before the page is painted: use the saved theme, or the device setting, so there's
// never a flash of the wrong theme. ThemeSwitch.js uses the same rule.
const setThemeEarly = `(function () {
  var theme;
  try { theme = localStorage.getItem("theme"); } catch (e) {}
  if (theme !== "light" && theme !== "dark") {
    theme = window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }
  document.documentElement.dataset.theme = theme;
})();`;

export default function RootLayout({ children }) {
  return (
    // data-theme is deliberately not set here: the script above owns it. If React set it,
    // pages that render fully in the browser (like the 404 page) would reset the theme.
    // Without the attribute, the dark colours apply (they're the :root defaults).
    <html lang="en-GB" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: setThemeEarly }} />
      </head>
      <body className="flex min-h-screen flex-col">
        <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-bg focus:p-3">
          Skip to content
        </a>
        <div aria-hidden="true" className="h-[3px] bg-[linear-gradient(90deg,var(--power),transparent_35%,transparent_65%,var(--power))]" />
        <SessionProvider>
          <Header />
          <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6">
            {children}
          </main>
        </SessionProvider>
        <footer className="border-t border-line py-8 text-sm text-ink-soft">
          <div className="mx-auto max-w-6xl px-4 sm:px-6">
            Shopverse is a portfolio project. Payments run in test mode, and no real money is taken.
          </div>
        </footer>
      </body>
    </html>
  );
}
