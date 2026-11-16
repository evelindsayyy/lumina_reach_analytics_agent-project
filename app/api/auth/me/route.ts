import { authConfigFromEnv } from "@/lib/auth-core";
import { signedInEmail } from "@/lib/auth-server";

export const dynamic = "force-dynamic";

// What the UI may know about the session: whether sign-in is on, and who is
// signed in. Never a token.
export async function GET(): Promise<Response> {
  const enabled = authConfigFromEnv(process.env) !== null;
  const email = enabled ? await signedInEmail() : null;
  return Response.json({ enabled, signedIn: email !== null, email: email || null });
}
