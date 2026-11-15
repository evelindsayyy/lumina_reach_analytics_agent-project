import { agentRuntimeUrl, proxyChat } from "@/lib/agent-proxy";

// The chat UI's only backend call. The agent runs as its own runtime (locally
// on port 8080, deployed on Amazon Bedrock AgentCore), so this route forwards
// the request and streams the answer back. See lib/agent-proxy.ts.

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
// A turn runs several model and tool calls before the answer streams, so the
// function must outlive them. 300 s is the Vercel Hobby ceiling.
export const maxDuration = 300;

export async function POST(request: Request): Promise<Response> {
  return proxyChat(await request.text(), {
    url: agentRuntimeUrl(process.env),
    signal: request.signal,
  });
}
