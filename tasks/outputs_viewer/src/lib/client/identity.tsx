"use client";
import * as React from "react";

const STORAGE_KEY = "outputs_viewer_user";

/** trim, lowercase, strip all non-alphanumerics — the canonical identity. */
export function normalizeUsername(raw: string): string {
  return raw.trim().toLowerCase().replace(/[^a-z0-9]/g, "");
}

interface IdentityCtx {
  /** normalized username, or null while unknown / logged out */
  user: string | null;
  /** true once localStorage has been consulted (avoids SSR flash) */
  ready: boolean;
  setUser: (raw: string) => void;
  clearUser: () => void;
}

const Ctx = React.createContext<IdentityCtx>({
  user: null,
  ready: false,
  setUser: () => {},
  clearUser: () => {},
});

export function IdentityProvider({ children }: { children: React.ReactNode }) {
  const [user, setUserState] = React.useState<string | null>(null);
  const [ready, setReady] = React.useState(false);

  React.useEffect(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored) setUserState(normalizeUsername(stored) || null);
    setReady(true);
  }, []);

  const setUser = React.useCallback((raw: string) => {
    const norm = normalizeUsername(raw);
    if (!norm) return;
    window.localStorage.setItem(STORAGE_KEY, norm);
    setUserState(norm);
  }, []);

  const clearUser = React.useCallback(() => {
    window.localStorage.removeItem(STORAGE_KEY);
    setUserState(null);
  }, []);

  const value = React.useMemo(
    () => ({ user, ready, setUser, clearUser }),
    [user, ready, setUser, clearUser],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useIdentity(): IdentityCtx {
  return React.useContext(Ctx);
}
