"use client"

import Hero from "./_components/Hero"
import type { SiteConfig } from "@/lib/site/schema"

export default function HomePageContent({
  site,
  businessContext,
}: {
  site: SiteConfig
  businessContext: string
}) {
  // A results page ends in a quiet grey footer bar; so does this one.
  return (
    <div className="min-h-screen bg-white text-primary font-body flex flex-col">
      <div className="flex-1">
        <Hero site={site} businessContext={businessContext} />
      </div>

      <footer className="py-5 px-4 sm:px-6 lg:px-8 border-t border-border bg-surface">
        <p className="max-w-6xl mx-auto text-sm text-muted-foreground">
          &copy; {new Date().getFullYear()} {site.brand.footerName}. All rights reserved.
        </p>
      </footer>
    </div>
  )
}
