import { cookies } from "next/headers";

import { authConfigFromEnv, logoutUrl } from "@/lib/auth-core";
import { clearTokens } from "@/lib/auth-server";

export const dynamic = "force-dynamic";

// Forget the tokens here, then end the user pool's session too, so the next
// sign-in asks for the password again.
export async function GET(request: Request): Promise<Response> {
  const origin = new URL(request.url).origin;
  clearTokens(await cookies());
  const config = authConfigFromEnv(process.env);
  return Response.redirect(config ? logoutUrl(config, origin) : `${origin}/`, 302);
}
