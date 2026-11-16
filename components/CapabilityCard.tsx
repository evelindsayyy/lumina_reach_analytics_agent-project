"use client"

import ConceptTooltip from "@/components/ConceptTooltip"
import { getIcon } from "@/lib/icons"
import { highlightSegments } from "@/lib/search-highlight"
import type { Capability } from "@/lib/site/schema"

/** `Attribution Truth` -> `attribution-truth`, for a result's display path. */
function slug(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")
}

/** `text` with the words matching `terms` marked, as a results page marks them. */
function Highlighted({ text, terms }: { text: string; terms: readonly string[] }) {
  return (
    <>
      {highlightSegments(text, terms).map((segment, index) =>
        segment.match ? (
          <mark key={index} className="bg-accent text-primary rounded-sm px-0.5 -mx-0.5">
            {segment.text}
          </mark>
        ) : (
          <span key={index}>{segment.text}</span>
        ),
      )}
    </>
  )
}

/**
 * One of the app's four business lines, with an explanation behind it.
 *
 * The home page and the agent's welcome screen both show these four, at
 * different sizes. One component rather than two so they cannot drift: the
 * previous arrangement had `home.capabilities` and `chat.insights` as separate
 * config, and they had already drifted.
 *
 * Drawn as a search result: a display path, a title in link colour, a snippet.
 * `title` is a concept name and is therefore unreadable to anyone outside the
 * domain. `subtitle` is the one-line translation; the tooltip is the paragraph
 * behind it, on hover, focus, or tap.
 */
export default function CapabilityCard({
  capability,
  align = "start",
  compact = false,
  site = "lumina-reach",
  label,
  highlight = [],
  className = "",
}: {
  capability: Capability
  /** Which edge the tooltip hangs from while the grid is two columns wide. */
  align?: "start" | "end"
  /** The agent's welcome screen has less room than the home page. */
  compact?: boolean
  /** The first part of the display path. */
  site?: string
  /** A tag before the path, such as "Sponsored" on the first result. */
  label?: string
  /** Query terms to mark in the title and snippet. */
  highlight?: readonly string[]
  className?: string
}) {
  const Icon = getIcon(capability.icon)

  return (
    <ConceptTooltip
      text={capability.tooltip}
      align={align}
      className={`group block cursor-help rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-brand-light focus-visible:ring-offset-4 ${className}`}
    >
      <span className={`flex items-center gap-2 ${compact ? "mb-1" : "mb-1.5"}`}>
        <span
          className={`flex items-center justify-center shrink-0 rounded-full bg-surface border border-border ${
            compact ? "w-5 h-5" : "w-7 h-7"
          }`}
        >
          <Icon className={`text-brand ${compact ? "w-3 h-3" : "w-3.5 h-3.5"}`} aria-hidden="true" />
        </span>
        <span className={`min-w-0 truncate font-mono text-path ${compact ? "text-[11px]" : "text-xs sm:text-sm"}`}>
          {label && <span className="font-body font-semibold text-primary mr-1.5">{label} ·</span>}
          {site} › {slug(capability.title)}
        </span>
      </span>
      {/* The dashed underline is the only thing telling a reader there is
          something to hover over. Without it the hint is invisible. */}
      <span
        className={`block w-fit font-display font-semibold text-brand underline decoration-dashed decoration-brand-soft underline-offset-4 group-hover:decoration-brand transition-colors ${
          compact ? "text-base leading-snug" : "text-xl sm:text-2xl leading-tight"
        }`}
      >
        <Highlighted text={capability.title} terms={highlight} />
      </span>
      <span
        className={`block text-muted-foreground ${compact ? "mt-1 text-xs leading-snug" : "mt-1.5 text-[15px] leading-relaxed"}`}
      >
        <Highlighted text={capability.subtitle} terms={highlight} />
      </span>
    </ConceptTooltip>
  )
}
