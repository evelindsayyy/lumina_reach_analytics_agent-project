"use client";

import type { UIMessage } from "ai";
import { motion } from "framer-motion";
import { User } from "lucide-react";
import { useState } from "react";

import { AssistantAvatar } from "./AssistantAvatar";
import { Markdown } from "./markdown";
import { cn } from "@/lib/utils";

/**
 * Collapsible component for displaying reasoning/thinking content.
 * Shows a summary by default, expands to show full content on click.
 */
const ReasoningBlock = ({ text }: { text: string }) => {
  const [isExpanded, setIsExpanded] = useState(false);

  // Truncate text for preview (first 100 chars)
  const previewText = text.length > 100 ? text.slice(0, 100) + "..." : text;

  return (
    <div className="border border-border rounded-lg bg-surface overflow-hidden">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full px-3 py-2 flex items-center gap-2 text-left hover:bg-muted transition-colors"
      >
        <svg
          className={cn(
            "w-4 h-4 text-muted-foreground transition-transform",
            isExpanded && "rotate-90"
          )}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        <span className="font-mono text-xs font-medium text-path">
          Thinking
        </span>
        {!isExpanded && (
          <span className="text-xs text-muted-foreground truncate flex-1">
            {previewText}
          </span>
        )}
      </button>
      {isExpanded && (
        <div className="px-3 py-2 border-t border-border">
          <div className="text-xs text-primary/80 whitespace-pre-wrap">
            {text}
          </div>
        </div>
      )}
    </div>
  );
};

export const PreviewMessage = ({
  message,
  append,
}: {
  message: UIMessage;
  append?: (message: any) => Promise<string | null | undefined>;
}) => {
  return (
    <motion.div
      className="w-full mx-auto max-w-3xl group/message"
      initial={{ y: 5, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      data-role={message.role}
    >
      <div
        className={cn(
          "flex gap-3 w-full",
          message.role === "user" ? "justify-end" : "justify-start"
        )}
      >
        {message.role === "assistant" && <AssistantAvatar />}

        <div
          className={cn(
            "flex flex-col gap-2 max-w-[85%] sm:max-w-[75%] p-4",
            message.role === "user"
              ? "bg-primary text-white rounded-2xl rounded-br-md"
              : "bg-white border border-border rounded-2xl rounded-bl-md"
          )}
        >
          {/* AI SDK v5: Use parts instead of content */}
          {message.parts && message.parts.length > 0 && (
            <div className="flex flex-col gap-4">
              {message.parts.map((part: any, index: number) => {
                // Render reasoning/thinking content
                if (part.type === 'reasoning' && part.text) {
                  return (
                    <ReasoningBlock key={index} text={part.text} />
                  );
                }
                // Render text content
                if (part.type === 'text' && part.text) {
                  return (
                    <div
                      key={index}
                      className={cn(
                        message.role === "assistant"
                          ? "text-primary"
                          : "text-white"
                      )}
                    >
                      <Markdown
                        onQuestionClick={(question) => {
                          append?.({
                            role: 'user',
                            content: question,
                          });
                        }}
                      >
                        {part.text}
                      </Markdown>
                    </div>
                  );
                }
                return null;
              })}
            </div>
          )}
        </div>

        {/* User Avatar - Right side */}
        {message.role === "user" && (
          <div className="w-8 h-8 flex items-center justify-center border border-border shrink-0 rounded-full bg-surface">
            <User className="w-4 h-4 text-muted-foreground" aria-label="You" />
          </div>
        )}
      </div>
    </motion.div>
  );
};

export const ThinkingMessage = () => {
  const role = "assistant";

  return (
    <motion.div
      className="w-full mx-auto max-w-3xl group/message"
      initial={{ y: 5, opacity: 0 }}
      animate={{ y: 0, opacity: 1, transition: { delay: 1 } }}
      data-role={role}
    >
      <div className="flex gap-3 w-full justify-start">
        <AssistantAvatar />

        <div className="bg-white border border-border rounded-2xl rounded-bl-md p-4">
          <div className="flex items-center gap-2 text-muted-foreground">
            <span className="inline-block w-2 h-2 bg-brand rounded-full animate-pulse" />
            <span className="font-display text-sm">Thinking...</span>
          </div>
        </div>
      </div>
    </motion.div>
  );
};
