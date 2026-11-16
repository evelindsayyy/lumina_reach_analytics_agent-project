// The session cookies: set after sign-in, read (and refreshed) by /api/chat,
// cleared at sign-out. SERVER ONLY. The pure parts live in auth-core.ts.

import { cookies } from "next/headers";

import {
  COOKIE_ACCESS,
  COOKIE_EMAIL,
  COOKIE_REFRESH,
  REFRESH_MAX_AGE_SECONDS,
  jwtClaims,
  needsRefresh,
  refreshBody,
  requestTokens,
  type AuthConfig,
  type TokenSet,
} from "./auth-core";

type CookieStore = Awaited<ReturnType<typeof cookies>>;

/** httpOnly (no script reads it), Secure off only on plain-http localhost. */
export function cookieOptions(maxAge: number, secure: boolean) {
  return { httpOnly: true, secure, sameSite: "lax" as const, path: "/", maxAge };
}

export function isSecureOrigin(origin: string): boolean {
  return origin.startsWith("https://");
}

/** Store a token set; the refresh token and email only when the set has them. */
export function storeTokens(store: CookieStore, tokens: TokenSet, secure: boolean): void {
  store.set(COOKIE_ACCESS, tokens.accessToken, cookieOptions(tokens.expiresIn, secure));
  if (tokens.refreshToken) {
    store.set(COOKIE_REFRESH, tokens.refreshToken, cookieOptions(REFRESH_MAX_AGE_SECONDS, secure));
  }
  const email = tokens.idToken ? jwtClaims(tokens.idToken)?.email : undefined;
  if (typeof email === "string") {
    store.set(COOKIE_EMAIL, email, cookieOptions(REFRESH_MAX_AGE_SECONDS, secure));
  }
}

export function clearTokens(store: CookieStore): void {
  for (const name of [COOKIE_ACCESS, COOKIE_REFRESH, COOKIE_EMAIL]) store.delete(name);
}

/**
 * A usable access token for this request: the stored one, or a fresh one
 * from the refresh token when it is about to expire. Null means signed out.
 */
export async function validAccessToken(config: AuthConfig, secure: boolean): Promise<string | null> {
  const store = await cookies();
  const access = store.get(COOKIE_ACCESS)?.value;
  if (!needsRefresh(access, Date.now() / 1000)) return access ?? null;
  const refresh = store.get(COOKIE_REFRESH)?.value;
  if (!refresh) return null;
  const tokens = await requestTokens(config, refreshBody(config, refresh));
  if (!tokens) {
    clearTokens(store);
    return null;
  }
  storeTokens(store, tokens, secure);
  return tokens.accessToken;
}

/** Who is signed in, for the UI: the email, or null. Never a token. */
export async function signedInEmail(): Promise<string | null> {
  const store = await cookies();
  if (!store.get(COOKIE_REFRESH) && !store.get(COOKIE_ACCESS)) return null;
  return store.get(COOKIE_EMAIL)?.value ?? "";
}
