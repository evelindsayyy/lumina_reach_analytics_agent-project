"use client";

import { useEffect, useRef } from "react";
import { Search } from "lucide-react";

import { RenderBadge } from "./RenderBadge";
import { nextQuestions } from "@/lib/next-questions";
import type { SuggestedAction } from "@/lib/site/schema";

/**
 * When to bring the questions into view: at once, and again after the
 * answer's charts and diagrams (loaded on demand) have laid out and grown it.
 */
const SCROLL_AFTER_MS = [100, 1200];

/**
 * Two or three example questions under the latest answer, so a visitor never
 * has to invent the next one. Drawn like the start screen's examples (related
 * searches); deployed, each replays a recorded answer at no cost.
 */
export function NextQuestions({
  label,
  examples,
  asked,
  onAsk,
}: {
  label: string;
  examples: SuggestedAction[];
  /** Every question the user has sent in this chat. */
  asked: string[];
  onAsk: (question: string) => void;
}) {
  const ref = useRef<HTMLElement>(null);
  const picked = nextQuestions(examples, asked);

  // They appear once the answer has finished, below the fold more often than
  // not; bring them into view after the answer's charts have settled.
  useEffect(() => {
    const timers = SCROLL_AFTER_MS.map((ms) =>
      setTimeout(() => ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }), ms),
    );
    return () => timers.forEach(clearTimeout);
  }, []);

  if (picked.length === 0) return null;

  return (
    <nav ref={ref} aria-label={label} className="w-full mx-auto max-w-3xl pl-11 scroll-mb-6">
      <p className="mb-2 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">{label}</p>
      <ul className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
        {picked.map((example) => (
          <li key={example.title}>
            <button
              type="button"
              onClick={() => onAsk(example.action)}
              className="group flex items-center gap-2 w-full sm:w-auto text-left rounded-full border border-border bg-white px-4 py-2 text-sm text-primary hover:border-brand-soft hover:bg-surface transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-light"
            >
              <Search className="w-3.5 h-3.5 shrink-0 text-muted-foreground group-hover:text-brand transition-colors" aria-hidden="true" />
              <span className="min-w-0">{example.label}</span>
              <RenderBadge render={example.render} />
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}
