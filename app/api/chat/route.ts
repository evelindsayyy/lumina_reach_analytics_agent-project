import {
  authConfigFromEnv,
  invocationUrl,
  jwtClaims,
  runtimeSessionId,
} from "@/lib/auth-core";
import { isSecureOrigin, validAccessToken } from "@/lib/auth-server";
import {
  SIGN_IN_REQUIRED_MESSAGE,
  SSE_HEADERS,
  agentRuntimeUrl,
  chatIdOf,
  proxyChat,
  textStreamResponse,
} from "@/lib/agent-proxy";
import { demoStreamEvents, demoStreamResponse, findDemoAnswer, type DemoAnswers } from "@/lib/demo-answers";
import recordedDemos from "@/data/demo-answers.json";

// The chat UI's only backend call. The agent runs as its own runtime (locally
// on port 8080, deployed on Amazon Bedrock AgentCore), so this route forwards
// the request and streams the answer back. See lib/agent-proxy.ts.
//
// Deployed (COGNITO_* and AGENT_RUNTIME_ARN set), it forwards the signed-in
// user's access token: AgentCore's JWT authorizer checks it before the agent
// sees the request, so this tier holds no AWS credential and no secret.
//
// Deployed, a new chat that asks one of the example questions replays the
// answer recorded from the live agent instead (lib/demo-answers.ts): no
// sign-in and no cost, so every visitor sees it work even after the month's
// budget is spent. Locally every question is live.

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
// A turn runs several model and tool calls before the answer streams, so the
// function must outlive them. 300 s is the Vercel Hobby ceiling.
export const maxDuration = 300;

export async function POST(request: Request): Promise<Response> {
  const body = await request.text();
  const auth = authConfigFromEnv(process.env);
  const arn = process.env.AGENT_RUNTIME_ARN;
  if (!auth || !arn) {
    return proxyChat(body, { url: agentRuntimeUrl(process.env), signal: request.signal });
  }

  const demos = recordedDemos as DemoAnswers;
  const demo = findDemoAnswer(body, demos);
  if (demo) return demoStreamResponse(demoStreamEvents(demo, demos), SSE_HEADERS);

  const token = await validAccessToken(auth, isSecureOrigin(new URL(request.url).origin));
  if (!token) return textStreamResponse(SIGN_IN_REQUIRED_MESSAGE);
  const sub = String(jwtClaims(token)?.sub ?? "anonymous");
  return proxyChat(body, {
    url: invocationUrl(arn),
    headers: {
      authorization: `Bearer ${token}`,
      "x-amzn-bedrock-agentcore-runtime-session-id": runtimeSessionId(sub, chatIdOf(body) || "chat"),
    },
    signal: request.signal,
  });
}
