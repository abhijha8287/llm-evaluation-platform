"use client";

import { createContext, useContext, useSyncExternalStore, type ReactNode } from "react";

const TOKEN_STORAGE_KEY = "llm_eval_platform_token";

// D10: login-only, single seeded demo user — no registration flow exists on
// the backend, so there's nothing here beyond login/logout. Token lives in
// localStorage, not an httpOnly cookie — simplest option for a portfolio
// demo with no sensitive user data; a real multi-tenant product would move
// this to httpOnly cookies + CSRF protection.
//
// useSyncExternalStore, not useState+useEffect — localStorage is an
// external store, and syncing React state from one via an effect that calls
// setState synchronously is exactly the anti-pattern
// eslint-plugin-react-hooks' set-state-in-effect rule flags (real behavior
// issue, not just style: it can trigger a cascading extra render).
// useSyncExternalStore also handles the server/client snapshot difference
// correctly on its own — no separate isLoading flag needed to avoid a
// hydration mismatch.
function subscribe(callback: () => void) {
  window.addEventListener("storage", callback);
  return () => window.removeEventListener("storage", callback);
}

function getSnapshot(): string | null {
  return window.localStorage.getItem(TOKEN_STORAGE_KEY);
}

function getServerSnapshot(): string | null {
  return null;
}

interface AuthContextValue {
  token: string | null;
  setToken: (token: string | null) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const token = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const setToken = (next: string | null) => {
    if (next) {
      window.localStorage.setItem(TOKEN_STORAGE_KEY, next);
    } else {
      window.localStorage.removeItem(TOKEN_STORAGE_KEY);
    }
    // The native "storage" event only fires in OTHER tabs, not the one that
    // made the change — dispatch manually so this tab's own subscriber
    // (and therefore this render) picks up the change too.
    window.dispatchEvent(new StorageEvent("storage"));
  };

  return <AuthContext.Provider value={{ token, setToken }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
