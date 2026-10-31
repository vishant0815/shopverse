"use client";

// Signed-in user and cart size, shared by every page.

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, refreshAccessToken, setAccessToken, setSessionEndedHandler } from "./api";

const SessionContext = createContext(null);

export function SessionProvider({ children }) {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);
  const [cartCount, setCartCount] = useState(0);

  const refreshCart = useCallback(async () => {
    try {
      const cart = await api("/api/v1/cart/");
      setCartCount(cart.items.reduce((sum, item) => sum + item.quantity, 0));
    } catch {
      setCartCount(0);
    }
  }, []);

  // On first load, try the refresh cookie: if it's valid the user is still signed in.
  useEffect(() => {
    setSessionEndedHandler(() => {
      setUser(null);
      setCartCount(0);
    });
    (async () => {
      if (await refreshAccessToken()) {
        try {
          setUser(await api("/api/v1/users/me/"));
          await refreshCart();
        } catch {
          setUser(null);
        }
      }
      setReady(true);
    })();
  }, [refreshCart]);

  const signIn = useCallback(async (path, body) => {
    const data = await api(path, { method: "POST", body, auth: false });
    setAccessToken(data.access);
    setUser(data.user);
    await refreshCart();
    return data.user;
  }, [refreshCart]);

  const value = useMemo(() => ({
    user,
    ready,
    cartCount,
    refreshCart,
    login: (email, password) => signIn("/api/v1/auth/login/", { email, password }),
    register: (details) => signIn("/api/v1/auth/register/", details),
    logout: async () => {
      await api("/api/v1/auth/logout/", { method: "POST", auth: false }).catch(() => {});
      setAccessToken(null);
      setUser(null);
      setCartCount(0);
    },
    setUser,
  }), [user, ready, cartCount, refreshCart, signIn]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const context = useContext(SessionContext);
  if (!context) throw new Error("useSession must be used inside SessionProvider");
  return context;
}
