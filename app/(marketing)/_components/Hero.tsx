"use client"

import { useCallback, useState } from "react"
import Link from "next/link"
import { ArrowRight, BookOpen } from "lucide-react"

import BusinessContextModal from "@/components/BusinessContextModal"
import CapabilityCard from "@/components/CapabilityCard"
import { queryTerms } from "@/lib/search-highlight"
import type { SiteConfig } from "@/lib/site/schema"

import SearchBox from "./SearchBox"

/**
 * The home page as a search results page (see the tone note in
 * tailwind.config.ts): the question goes in the search box, the four business
 * threads come back as results with the words of the question marked, and the
 * facts about the product sit in a knowledge panel beside them.
 */
export default function Hero({
  site,
  businessContext,
}: {
  site: SiteConfig
  /** Raw Markdown of `data/business-context.md`, read on the server. */
  businessContext: string
}) {
  const [contextOpen, setContextOpen] = useState(false)
  const [terms, setTerms] = useState<string[]>([])
  const onQueryChange = useCallback((query: string) => setTerms(queryTerms(query)), [])

  const { brand, home, capabilities, chat } = site
  const domain = `${brand.logoPrefix}${brand.logoAccent}`.toLowerCase()

  return (
    <section className="pt-28 sm:pt-32 pb-20 px-4 sm:px-6 lg:px-8 bg-white">
      <div className="max-w-6xl mx-auto grid gap-12 lg:gap-16 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 max-w-2xl">
          <p className="font-mono text-xs uppercase tracking-[0.18em] text-muted-foreground mb-4">
            {home.tagline}
          </p>
          <h1 className="font-display font-bold text-primary text-[2.6rem] leading-[1.02] sm:text-6xl tracking-tight mb-8">
            {home.headline.prefix}
            <mark className="bg-accent text-primary rounded-md px-2 -mx-1 box-decoration-clone">
              {home.headline.accent}
            </mark>
          </h1>

          <SearchBox
            placeholder={home.search.placeholder}
            suggestionsLabel={home.search.suggestionsLabel}
            submitLabel={home.cta.title}
            suggestions={chat.suggestedActions}
            onQueryChange={onQueryChange}
          />

          <p className="mt-4 mb-10 pl-5 font-mono text-xs text-muted-foreground">{home.search.resultsLine}</p>

          {/* The four business threads, as results. Same four on the agent's
              welcome screen, from the same `[[capabilities]]`. */}
          <ol className="space-y-8">
            {capabilities.map((capability, index) => (
              <li key={capability.title}>
                <CapabilityCard
                  capability={capability}
                  site={domain}
                  label={index === 0 ? home.search.sponsored : undefined}
                  highlight={terms}
                  className="w-fit max-w-full"
                />
              </li>
            ))}
          </ol>
        </div>

        {/* The knowledge panel: what this is, what it reads, what it runs on. */}
        <aside className="lg:pt-[7.25rem]">
          <div className="lg:sticky lg:top-24 rounded-2xl border border-border bg-white p-6">
            <p className="font-display text-2xl font-semibold text-primary">{brand.displayName}</p>
            <p className="font-mono text-xs text-path mt-1">{home.tagline}</p>

            <p className="mt-4 text-sm leading-relaxed text-primary/80">{home.description}</p>

            {/* One paragraph cannot carry a whole business domain; this opens
                the two or three screens that can. */}
            <button
              type="button"
              onClick={() => setContextOpen(true)}
              className="mt-4 inline-flex items-center gap-2 text-sm font-medium text-brand hover:underline underline-offset-4 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-light rounded-sm"
            >
              <BookOpen className="w-4 h-4" aria-hidden="true" />
              {home.businessContext.triggerLabel}
            </button>

            <dl className="mt-5 pt-5 border-t border-border space-y-3 text-sm">
              <div>
                <dt className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
                  {home.search.dataLabel}
                </dt>
                <dd className="mt-0.5 text-primary/80 leading-relaxed">{home.blurb}</dd>
              </div>
              <div>
                <dt className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
                  {home.search.stackLabel}
                </dt>
                <dd className="mt-1 flex flex-wrap gap-1.5">
                  {home.techStack.map((tech) => (
                    <span
                      key={tech}
                      className="px-2.5 py-0.5 rounded-full bg-surface border border-border text-xs text-primary/80"
                    >
                      {tech}
                    </span>
                  ))}
                </dd>
              </div>
            </dl>

            <Link
              href="/chat"
              className="group mt-6 flex items-center justify-between gap-3 rounded-xl bg-brand px-5 py-4 text-white hover:bg-brand-dark transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-light focus-visible:ring-offset-2"
            >
              <span>
                <span className="block font-display text-lg font-semibold">{home.cta.title}</span>
                <span className="block text-xs text-white/75">{home.cta.subtitle}</span>
              </span>
              <ArrowRight className="w-5 h-5 shrink-0 transition-transform group-hover:translate-x-1" aria-hidden="true" />
            </Link>
          </div>
        </aside>
      </div>

      <BusinessContextModal
        open={contextOpen}
        onClose={() => setContextOpen(false)}
        labels={home.businessContext}
        markdown={businessContext}
      />
    </section>
  )
}
