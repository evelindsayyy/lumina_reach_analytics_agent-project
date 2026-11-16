// Replays of the deployed agent's recorded answers to the example questions.
//
// The live demo runs on a small monthly budget shared by every visitor, so
// once it is spent a newcomer would see nothing work. The example questions on
// the chat's start screen therefore replay answers recorded from the deployed
// agent (`mise run ac-record-demos` writes data/demo-answers.json): no sign-in,
// no model call, no cost, and always there. Typed questions stay live.
//
// No imports on purpose, so `node --test` runs it directly (tests_node/).

export interface DemoAnswer {
  title: string;
  question: string;
  reasoning: string;
  answer: string;
  /** How long the live agent took. */
  seconds: number;
  inputTokens: number;
  outputTokens: number;
  /** The UTC date this answer was recorded (answers are re-recorded one at a time). */
  recordedAt?: string;
}

export interface DemoAnswers {
  /** The newest answer's recording date, or "" before the first one. */
  recordedAt: string;
  model: string;
  answers: DemoAnswer[];
}

/** Characters per replayed text delta. */
export const DEMO_CHUNK_CHARS = 80;
/** Pause between replayed events, so the answer arrives the way a live one does. */
export const DEMO_EVENT_DELAY_MS = 15;

interface RequestMessage {
  role?: unknown;
  parts?: unknown;
}

/**
 * The text of the one user message of a new chat's first request, or null
 * when the request is anything else (a follow-up, or not an AI SDK request).
 */
export function firstQuestionOf(body: string): string | null {
  let messages: unknown;
  try {
    messages = (JSON.parse(body) as { messages?: unknown }).messages;
  } catch {
    return null;
  }
  if (!Array.isArray(messages) || messages.length !== 1) return null;
  const message = messages[0] as RequestMessage;
  if (message?.role !== "user" || !Array.isArray(message.parts)) return null;
  return message.parts
    .filter((part: { type?: unknown }) => part?.type === "text")
    .map((part: { text?: unknown }) => (typeof part.text === "string" ? part.text : ""))
    .join("");
}

/** The recording for a new chat that asks an example question, else null. */
export function findDemoAnswer(body: string, demos: DemoAnswers): DemoAnswer | null {
  const question = firstQuestionOf(body)?.trim();
  if (!question) return null;
  return demos.answers.find((demo) => demo.question.trim() === question) ?? null;
}

/** The line above a replayed answer: what it is, and how to ask live. */
export function demoNote(demos: DemoAnswers, demo: DemoAnswer): string {
  return (
    `> **Recorded answer.** This replays what the live agent (Amazon Bedrock AgentCore + Snowflake) ` +
    `answered on ${demo.recordedAt || demos.recordedAt}, in ${Math.round(demo.seconds)} s. ` +
    `Sign in and type your own question for a live answer.\n\n`
  );
}

function sseEvent(payload: unknown): string {
  return `data: ${JSON.stringify(payload)}\n\n`;
}

/** The replay as AI SDK v5 UI message stream events, the answer in pieces. */
export function demoStreamEvents(demo: DemoAnswer, demos: DemoAnswers, chunkChars = DEMO_CHUNK_CHARS): string[] {
  const events: string[] = [];
  if (demo.reasoning) {
    events.push(sseEvent({ type: "reasoning-start", id: "demo-reasoning" }));
    events.push(sseEvent({ type: "reasoning-delta", id: "demo-reasoning", delta: demo.reasoning }));
    events.push(sseEvent({ type: "reasoning-end", id: "demo-reasoning" }));
  }
  const text = demoNote(demos, demo) + demo.answer;
  events.push(sseEvent({ type: "text-start", id: "demo-text" }));
  for (let start = 0; start < text.length; start += chunkChars) {
    events.push(sseEvent({ type: "text-delta", id: "demo-text", delta: text.slice(start, start + chunkChars) }));
  }
  events.push(sseEvent({ type: "text-end", id: "demo-text" }));
  events.push(sseEvent({ type: "finish", finishReason: "stop" }));
  events.push("data: [DONE]\n\n");
  return events;
}

/** A streaming response that sends `events` one by one, `delayMs` apart. */
export function demoStreamResponse(
  events: string[],
  headers: Readonly<Record<string, string>>,
  delayMs = DEMO_EVENT_DELAY_MS,
): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      for (const event of events) {
        controller.enqueue(encoder.encode(event));
        if (delayMs > 0) await new Promise((resolve) => setTimeout(resolve, delayMs));
      }
      controller.close();
    },
  });
  return new Response(stream, { status: 200, headers });
}
