import "./globals.css";

import Header from "@/components/Header";
import { SessionProvider } from "@/lib/session";

export const metadata = {
  title: { default: "Shopverse", template: "%s | Shopverse" },
  description: "Phones, clothes and home goods from independent sellers, paid for in one checkout.",
  icons: { icon: "/favicon.svg" },
};

export default function RootLayout({ children }) {
  return (
    <html lang="en-GB">
      <body className="flex min-h-screen flex-col">
        <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:bg-white focus:p-2">
          Skip to content
        </a>
        <SessionProvider>
          <Header />
          <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">
            {children}
          </main>
        </SessionProvider>
        <footer className="border-t border-line py-8 text-sm text-ink-soft">
          <div className="mx-auto max-w-6xl px-4">
            Shopverse is a portfolio project. Payments run in test mode, and no real money is taken.
          </div>
        </footer>
      </body>
    </html>
  );
}
