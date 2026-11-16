// Tests for lib/auth-core.ts: the sign-in protocol's pure parts. Fictional
// domain and client; no network (the token endpoint is a stub fetch).

import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";

import {
  CALLBACK_PATH,
  authConfigFromEnv,
  authorizeUrl,
  codeExchangeBody,
  invocationUrl,
  jwtClaims,
  logoutUrl,
  needsRefresh,
  pkceChallenge,
  randomToken,
  refreshBody,
  requestTokens,
  runtimeSessionId,
} from "../lib/auth-core.ts";

const CONFIG = { cognitoDomain: "https://acme.auth.us-east-2.amazoncognito.com", clientId: "acmeclient" };
const ORIGIN = "https://acme.example";

function b64url(text) {
  return Buffer.from(text).toString("base64url");
}
function jwt(claims) {
  return `${b64url('{"alg":"RS256"}')}.${b64url(JSON.stringify(claims))}.sig`;
}

test("sign-in is off unless both settings are present", () => {
  assert.equal(authConfigFromEnv({}), null);
  assert.equal(authConfigFromEnv({ COGNITO_DOMAIN: "https://x" }), null);
  assert.deepEqual(authConfigFromEnv({ COGNITO_DOMAIN: "https://x/", COGNITO_CLIENT_ID: "c" }), {
    cognitoDomain: "https://x",
    clientId: "c",
  });
});

test("random tokens are url-safe and differ", () => {
  const a = randomToken(32);
  assert.match(a, /^[A-Za-z0-9_-]{43}$/);
  assert.notEqual(a, randomToken(32));
});

test("the PKCE challenge is base64url(sha256(verifier)) (RFC 7636 appendix B)", async () => {
  const verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk";
  assert.equal(await pkceChallenge(verifier), "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM");
  assert.equal(await pkceChallenge("x"), createHash("sha256").update("x").digest("base64url"));
});

test("the authorize URL asks for a code with S256 PKCE and comes back to the callback", () => {
  const url = new URL(authorizeUrl(CONFIG, ORIGIN, "st", "ch"));
  assert.equal(url.origin + url.pathname, `${CONFIG.cognitoDomain}/oauth2/authorize`);
  const p = Object.fromEntries(url.searchParams);
  assert.deepEqual(p, {
    response_type: "code",
    client_id: "acmeclient",
    redirect_uri: `${ORIGIN}${CALLBACK_PATH}`,
    scope: "openid email profile",
    state: "st",
    code_challenge: "ch",
    code_challenge_method: "S256",
  });
});

test("the code exchange carries the verifier and the same redirect URI", () => {
  const p = Object.fromEntries(new URLSearchParams(codeExchangeBody(CONFIG, ORIGIN, "c0de", "v3r")));
  assert.deepEqual(p, {
    grant_type: "authorization_code",
    client_id: "acmeclient",
    code: "c0de",
    redirect_uri: `${ORIGIN}${CALLBACK_PATH}`,
    code_verifier: "v3r",
  });
  assert.equal(new URLSearchParams(refreshBody(CONFIG, "r")).get("grant_type"), "refresh_token");
});

test("logout returns to the home page", () => {
  const url = new URL(logoutUrl(CONFIG, ORIGIN));
  assert.equal(url.pathname, "/logout");
  assert.equal(url.searchParams.get("logout_uri"), `${ORIGIN}/`);
});

test("the token endpoint's answer becomes a token set; any failure is null", async () => {
  let seen;
  const ok = async (url, init) => {
    seen = { url, init };
    return Response.json({ access_token: "a", refresh_token: "r", id_token: "i", expires_in: 3600 });
  };
  assert.deepEqual(await requestTokens(CONFIG, "body", ok), {
    accessToken: "a",
    refreshToken: "r",
    idToken: "i",
    expiresIn: 3600,
  });
  assert.equal(seen.url, `${CONFIG.cognitoDomain}/oauth2/token`);
  assert.equal(seen.init.headers["content-type"], "application/x-www-form-urlencoded");
  assert.equal(await requestTokens(CONFIG, "b", async () => new Response("no", { status: 400 })), null);
  assert.equal(await requestTokens(CONFIG, "b", async () => Response.json({ nope: 1 })), null);
  assert.equal(
    await requestTokens(CONFIG, "b", async () => {
      throw new TypeError("fetch failed");
    }),
    null,
  );
});

test("JWT claims decode, including non-ASCII; garbage is null", () => {
  assert.deepEqual(jwtClaims(jwt({ sub: "u1", email: "é@acme.example" })), { sub: "u1", email: "é@acme.example" });
  for (const bad of ["x", "a.b", "a.!!.c", `a.${b64url("[1]")}.c`]) assert.equal(jwtClaims(bad), null);
});

test("a token is refreshed when missing or within a minute of expiry", () => {
  const now = 1_000_000;
  assert.equal(needsRefresh(undefined, now), true);
  assert.equal(needsRefresh("garbage", now), true);
  assert.equal(needsRefresh(jwt({ exp: now + 30 }), now), true);
  assert.equal(needsRefresh(jwt({ exp: now + 600 }), now), false);
});

test("a session id is per user and conversation, and long enough for AgentCore", () => {
  const a = runtimeSessionId("11111111-2222-3333-4444-555555555555", "chat1");
  assert.ok(a.length >= 33);
  assert.notEqual(a, runtimeSessionId("99999999-2222-3333-4444-555555555555", "chat1"));
  assert.equal(runtimeSessionId("u", "c").length, 33);
  assert.match(runtimeSessionId("u/x", "c?y"), /^[A-Za-z0-9-]+$/);
});

test("the invocation URL is AgentCore's endpoint in the runtime's region", () => {
  const arn = "arn:aws:bedrock-agentcore:us-east-2:111122223333:runtime/acme-x1";
  assert.equal(
    invocationUrl(arn),
    "https://bedrock-agentcore.us-east-2.amazonaws.com/runtimes/arn%3Aaws%3Abedrock-agentcore%3Aus-east-2%3A111122223333%3Aruntime%2Facme-x1/invocations?qualifier=DEFAULT",
  );
});
