// Sign-in with the deployment's Cognito user pool: authorization code + PKCE,
// done entirely on the server. The browser only ever holds httpOnly cookies,
// so no script on the page can read a token.
//
// Everything here is a pure function of its arguments (plus Web Crypto for
// randomness), with no imports, so `node --test` runs it directly
// (tests_node/). The cookie plumbing that needs Next.js lives in auth-server.ts.

/** The web app's view of the deployment. None of it is a secret. */
export interface AuthConfig {
  /** The managed login domain, e.g. https://<prefix>.auth.<region>.amazoncognito.com */
  cognitoDomain: string;
  /** The user pool's public web client (no secret: PKCE instead). */
  clientId: string;
}

export interface TokenSet {
  accessToken: string;
  /** Absent on a refresh, which returns no new refresh token. */
  refreshToken?: string;
  idToken?: string;
  /** Seconds the access token lives. */
  expiresIn: number;
}

export const CALLBACK_PATH = "/api/auth/callback";
export const SCOPES = "openid email profile";

export const COOKIE_ACCESS = "lr_access";
export const COOKIE_REFRESH = "lr_refresh";
export const COOKIE_EMAIL = "lr_email";
export const COOKIE_PKCE = "lr_pkce";

/** How long a refresh token is kept: the client's refresh token validity. */
export const REFRESH_MAX_AGE_SECONDS = 30 * 24 * 3600;
/** How long a started sign-in may take before its PKCE cookie lapses. */
export const PKCE_MAX_AGE_SECONDS = 600;
/** Refresh this long before the access token expires, so no call races it. */
export const REFRESH_LEEWAY_SECONDS = 60;

/** The auth config from the environment, or null when sign-in is off (local development). */
export function authConfigFromEnv(env: Readonly<Record<string, string | undefined>>): AuthConfig | null {
  const cognitoDomain = (env.COGNITO_DOMAIN || "").replace(/\/+$/, "");
  const clientId = env.COGNITO_CLIENT_ID || "";
  return cognitoDomain && clientId ? { cognitoDomain, clientId } : null;
}

function base64url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** A random URL-safe string of `bytes` random bytes. */
export function randomToken(bytes = 32): string {
  return base64url(crypto.getRandomValues(new Uint8Array(bytes)));
}

/** The S256 PKCE challenge of `verifier`. */
export async function pkceChallenge(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64url(new Uint8Array(digest));
}

export function redirectUri(origin: string): string {
  return `${origin}${CALLBACK_PATH}`;
}

export function authorizeUrl(config: AuthConfig, origin: string, state: string, challenge: string): string {
  const params = new URLSearchParams({
    response_type: "code",
    client_id: config.clientId,
    redirect_uri: redirectUri(origin),
    scope: SCOPES,
    state,
    code_challenge: challenge,
    code_challenge_method: "S256",
  });
  return `${config.cognitoDomain}/oauth2/authorize?${params}`;
}

export function logoutUrl(config: AuthConfig, origin: string): string {
  const params = new URLSearchParams({ client_id: config.clientId, logout_uri: `${origin}/` });
  return `${config.cognitoDomain}/logout?${params}`;
}

/** The form body exchanging an authorization code (with its PKCE verifier) for tokens. */
export function codeExchangeBody(config: AuthConfig, origin: string, code: string, verifier: string): string {
  return new URLSearchParams({
    grant_type: "authorization_code",
    client_id: config.clientId,
    code,
    redirect_uri: redirectUri(origin),
    code_verifier: verifier,
  }).toString();
}

export function refreshBody(config: AuthConfig, refreshToken: string): string {
  return new URLSearchParams({
    grant_type: "refresh_token",
    client_id: config.clientId,
    refresh_token: refreshToken,
  }).toString();
}

/**
 * POST a token request to the user pool. Returns null on any failure, which
 * every caller treats as "signed out".
 */
export async function requestTokens(
  config: AuthConfig,
  body: string,
  fetchImpl: typeof fetch = fetch,
): Promise<TokenSet | null> {
  try {
    const response = await fetchImpl(`${config.cognitoDomain}/oauth2/token`, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body,
    });
    if (!response.ok) {
      console.error(`[auth] token endpoint answered HTTP ${response.status}`);
      return null;
    }
    const data = (await response.json()) as Record<string, unknown>;
    if (typeof data.access_token !== "string") return null;
    return {
      accessToken: data.access_token,
      refreshToken: typeof data.refresh_token === "string" ? data.refresh_token : undefined,
      idToken: typeof data.id_token === "string" ? data.id_token : undefined,
      expiresIn: typeof data.expires_in === "number" ? data.expires_in : 3600,
    };
  } catch (error: unknown) {
    console.error("[auth] token endpoint unreachable", error);
    return null;
  }
}

/**
 * The claims of a JWT, decoded without checking its signature. Only for
 * reading tokens this server received straight from the user pool's token
 * endpoint over TLS; the agent's authorizer verifies every token it is sent.
 */
export function jwtClaims(token: string): Record<string, unknown> | null {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const json = atob(parts[1].replace(/-/g, "+").replace(/_/g, "/"));
    const bytes = Uint8Array.from(json, (c) => c.charCodeAt(0));
    const claims: unknown = JSON.parse(new TextDecoder().decode(bytes));
    return claims && typeof claims === "object" && !Array.isArray(claims) ? (claims as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

/** True when `token` is missing, undecodable, or expires within the leeway. */
export function needsRefresh(token: string | undefined, nowSeconds: number): boolean {
  if (!token) return true;
  const exp = jwtClaims(token)?.exp;
  return typeof exp !== "number" || exp - REFRESH_LEEWAY_SECONDS <= nowSeconds;
}

/**
 * The AgentCore session of one conversation of one user. AgentCore keeps a
 * session on one microVM, so a user's conversation stays warm, and two users
 * never share one. At least 33 characters, as AgentCore requires.
 */
export function runtimeSessionId(sub: string, chatId: string): string {
  const id = `${sub}-${chatId}`.replace(/[^A-Za-z0-9-]/g, "");
  return id.length >= 33 ? id : id.padEnd(33, "0");
}

/** AgentCore's HTTPS invocation endpoint of the runtime `arn`. */
export function invocationUrl(arn: string): string {
  const region = arn.split(":")[3];
  return `https://bedrock-agentcore.${region}.amazonaws.com/runtimes/${encodeURIComponent(arn)}/invocations?qualifier=DEFAULT`;
}
