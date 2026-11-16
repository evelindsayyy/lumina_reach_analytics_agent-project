"use client";

import { useEffect, useState } from "react";

/** What the UI knows about the session (from /api/auth/me): never a token. */
export interface AuthState {
  /** Sign-in is configured (deployed). Off locally, where nothing asks for it. */
  enabled: boolean;
  signedIn: boolean;
  email: string | null;
  loading: boolean;
}

const INITIAL: AuthState = { enabled: false, signedIn: false, email: null, loading: true };

export function useAuth(): AuthState {
  const [state, setState] = useState<AuthState>(INITIAL);
  useEffect(() => {
    let cancelled = false;
    fetch("/api/auth/me", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((data: Omit<AuthState, "loading">) => {
        if (!cancelled) setState({ ...data, loading: false });
      })
      .catch(() => {
        if (!cancelled) setState({ ...INITIAL, loading: false });
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return state;
}
