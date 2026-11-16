"use client"

import { useEffect, useId, useMemo, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { ArrowRight, Search } from "lucide-react"

import { saveChatDraft } from "@/lib/chat-draft"
import { queryTerms } from "@/lib/search-highlight"
import type { SuggestedAction } from "@/lib/site/schema"

/** Typing speed of the idle demo, and how long a finished question stays. */
const TYPE_MS = 45
const ERASE_MS = 18
const HOLD_MS = 2200
/** How many example questions the open box lists. */
const MAX_OPTIONS = 6

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches
}

/**
 * The idle box types the example questions one after another, the way a
 * search page shows what people ask. Returns the text typed so far.
 */
function useTypedQuestions(questions: string[], paused: boolean): string {
  const [typed, setTyped] = useState("")

  useEffect(() => {
    if (paused || questions.length === 0) return
    if (prefersReducedMotion()) {
      setTyped(questions[0])
      return
    }
    let question = 0
    let length = 0
    let erasing = false
    let timer: ReturnType<typeof setTimeout>

    const step = () => {
      const full = questions[question]
      if (!erasing && length < full.length) {
        length += 1
        timer = setTimeout(step, TYPE_MS)
      } else if (!erasing) {
        erasing = true
        timer = setTimeout(step, HOLD_MS)
      } else if (length > 0) {
        length -= 1
        timer = setTimeout(step, ERASE_MS)
      } else {
        erasing = false
        question = (question + 1) % questions.length
        timer = setTimeout(step, TYPE_MS * 6)
      }
      setTyped(full.slice(0, length))
    }
    timer = setTimeout(step, 600)
    return () => clearTimeout(timer)
  }, [questions, paused])

  return paused ? "" : typed
}

/**
 * The home page's front door: a search box over the agent's example
 * questions. Choosing one, or pressing Enter on your own, opens the chat with
 * the question waiting in the composer.
 */
export default function SearchBox({
  placeholder,
  suggestionsLabel,
  submitLabel,
  suggestions,
  onQueryChange,
}: {
  placeholder: string
  suggestionsLabel: string
  /** Names the button beside the box, for screen readers. */
  submitLabel: string
  suggestions: SuggestedAction[]
  /** The text in the box as it changes, typed by the reader or by the demo. */
  onQueryChange: (query: string) => void
}) {
  const router = useRouter()
  const listId = useId()
  const inputRef = useRef<HTMLInputElement>(null)
  const [value, setValue] = useState("")
  const [focused, setFocused] = useState(false)
  const [active, setActive] = useState(-1)

  const labels = useMemo(() => suggestions.map((s) => s.label), [suggestions])
  const typed = useTypedQuestions(labels, focused || value !== "")
  const query = value || typed

  useEffect(() => onQueryChange(query), [query, onQueryChange])

  const options = useMemo(() => {
    const terms = queryTerms(value)
    if (terms.length === 0) return suggestions.slice(0, MAX_OPTIONS)
    const text = (s: SuggestedAction) => `${s.label} ${s.title} ${s.action}`.toLowerCase()
    return suggestions.filter((s) => terms.some((t) => text(s).includes(t))).slice(0, MAX_OPTIONS)
  }, [suggestions, value])

  const open = focused && options.length > 0

  const ask = (question: string) => {
    if (!question.trim()) {
      inputRef.current?.focus()
      return
    }
    saveChatDraft(question.trim())
    router.push("/chat")
  }

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" && options.length > 0) {
      event.preventDefault()
      setActive((i) => (i + 1) % options.length)
    } else if (event.key === "ArrowUp" && options.length > 0) {
      event.preventDefault()
      setActive((i) => (i <= 0 ? options.length - 1 : i - 1))
    } else if (event.key === "Enter") {
      event.preventDefault()
      ask(open && active >= 0 ? options[active].action : value)
    } else if (event.key === "Escape") {
      setActive(-1)
      inputRef.current?.blur()
    }
  }

  return (
    // Above the results and their tooltips (z-30), which the open list covers.
    <div className="relative z-40 w-full">
      <div
        className={`flex items-center gap-3 h-14 pl-5 pr-2 bg-white border transition-shadow ${
          open
            ? "rounded-t-[28px] border-brand-soft border-b-transparent shadow-lg"
            : "rounded-full border-border shadow-sm hover:shadow-md"
        }`}
      >
        <Search className="w-5 h-5 shrink-0 text-muted-foreground" aria-hidden="true" />
        <div className="relative flex-1 min-w-0 h-full">
          <input
            ref={inputRef}
            type="text"
            role="combobox"
            aria-expanded={open}
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={open && active >= 0 ? `${listId}-${active}` : undefined}
            aria-label={placeholder}
            value={value}
            onChange={(e) => {
              setValue(e.target.value)
              setActive(-1)
            }}
            onFocus={() => setFocused(true)}
            onBlur={() => {
              setFocused(false)
              setActive(-1)
            }}
            onKeyDown={onKeyDown}
            className="w-full h-full bg-transparent text-base sm:text-lg text-primary outline-none placeholder:text-transparent"
            placeholder={placeholder}
          />
          {/* The idle demo is drawn over the empty box, never typed into it:
              the field stays empty and stays the reader's. */}
          {!value && (
            <span
              aria-hidden="true"
              className="pointer-events-none absolute inset-0 flex items-center text-base sm:text-lg truncate"
            >
              {focused || !typed ? (
                <span className="text-muted-foreground">{placeholder}</span>
              ) : (
                <span className="text-primary">
                  {typed}
                  <span className="inline-block w-[2px] h-[1.1em] align-[-0.15em] ml-0.5 bg-brand motion-safe:animate-pulse" />
                </span>
              )}
            </span>
          )}
        </div>
        <button
          type="button"
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => ask(value)}
          aria-label={submitLabel}
          className="flex items-center justify-center w-10 h-10 shrink-0 rounded-full bg-brand text-white hover:bg-brand-dark transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-light focus-visible:ring-offset-2"
        >
          <ArrowRight className="w-5 h-5" aria-hidden="true" />
        </button>
      </div>

      {open && (
        <div className="absolute left-0 right-0 top-full bg-white border border-t-0 border-brand-soft rounded-b-[28px] shadow-lg pb-3">
          <div className="mx-5 border-t border-border" />
          <p className="px-5 pt-3 pb-1 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
            {suggestionsLabel}
          </p>
          <ul id={listId} role="listbox" aria-label={suggestionsLabel}>
            {options.map((option, index) => (
              <li
                key={option.title}
                id={`${listId}-${index}`}
                role="option"
                aria-selected={index === active}
                onMouseDown={(e) => e.preventDefault()}
                onMouseEnter={() => setActive(index)}
                onClick={() => ask(option.action)}
                className={`flex items-center gap-3 px-5 py-2 cursor-pointer ${
                  index === active ? "bg-surface" : ""
                }`}
              >
                <Search className="w-4 h-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                <span className="flex-1 min-w-0 truncate text-primary">{option.label}</span>
                <span className="hidden sm:block shrink-0 font-mono text-xs text-path">{option.title}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
