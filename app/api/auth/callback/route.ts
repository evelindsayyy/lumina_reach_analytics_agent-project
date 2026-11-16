import { cookies } from "next/headers";

import { COOKIE_PKCE, authConfigFromEnv, codeExchangeBody, requestTokens } from "@/lib/auth-core";
import { isSecureOrigin, storeTokens } from "@/lib/auth-server";

export const dynamic = "force-dynamic";

// The managed login sends the browser back here with a code. The state must
// match the one this browser started with (no forged callback), and the code
// is exchanged with the PKCE verifier only this server holds.
export async function GET(request: Request): Promise<Response> {
  const url = new URL(request.url);
  const origin = url.origin;
  const config = authConfigFromEnv(process.env);
  const store = await cookies();
  const pending = store.get(COOKIE_PKCE)?.value;
  store.delete(COOKIE_PKCE);

  let started: { verifier?: string; state?: string } = {};
  try {
    started = pending ? JSON.parse(pending) : {};
  } catch {
    started = {};
  }
  const code = url.searchParams.get("code");
  if (!config || !code || !started.verifier || url.searchParams.get("state") !== started.state) {
    return Response.redirect(`${origin}/chat?signin=failed`, 302);
  }
  const tokens = await requestTokens(config, codeExchangeBody(config, origin, code, started.verifier));
  if (!tokens) return Response.redirect(`${origin}/chat?signin=failed`, 302);
  storeTokens(store, tokens, isSecureOrigin(origin));
  return Response.redirect(`${origin}/chat`, 302);
}
