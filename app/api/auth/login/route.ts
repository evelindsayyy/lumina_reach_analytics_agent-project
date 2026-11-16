import { cookies } from "next/headers";

import {
  COOKIE_PKCE,
  PKCE_MAX_AGE_SECONDS,
  authConfigFromEnv,
  authorizeUrl,
  pkceChallenge,
  randomToken,
} from "@/lib/auth-core";
import { cookieOptions, isSecureOrigin } from "@/lib/auth-server";

export const dynamic = "force-dynamic";

// Start a sign-in: remember a PKCE verifier and a state value in a short-lived
// httpOnly cookie, then send the browser to the user pool's managed login.
export async function GET(request: Request): Promise<Response> {
  const config = authConfigFromEnv(process.env);
  const origin = new URL(request.url).origin;
  if (!config) return Response.redirect(`${origin}/chat`, 302);

  const verifier = randomToken(48);
  const state = randomToken(24);
  const store = await cookies();
  store.set(COOKIE_PKCE, JSON.stringify({ verifier, state }), cookieOptions(PKCE_MAX_AGE_SECONDS, isSecureOrigin(origin)));
  return Response.redirect(authorizeUrl(config, origin, state, await pkceChallenge(verifier)), 302);
}
