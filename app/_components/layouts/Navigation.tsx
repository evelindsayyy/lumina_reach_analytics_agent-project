"use client"

import { useState } from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { Menu, X } from "lucide-react"

import { AuthStatus } from "@/components/AuthStatus"

/** One entry in the top bar. */
interface NavItem {
  label: string
  href: string
}

/**
 * The bar is the same on every page, and its two entries are the app's two
 * pages. Not authored copy: a dataset swap rewrites what the app is about,
 * not how many pages it has.
 */
const DEFAULT_NAV_ITEMS: NavItem[] = [
  { label: "Home", href: "/" },
  { label: "Chat", href: "/chat" },
]

export default function Navigation({
  items = DEFAULT_NAV_ITEMS,
  logoPrefix,
  logoAccent,
}: {
  items?: NavItem[]
  /** The wordmark, split so the two halves can be coloured differently. */
  logoPrefix: string
  logoAccent: string
}) {
  const [isMenuOpen, setIsMenuOpen] = useState(false)
  const pathname = usePathname()

  const isActive = (href: string) => {
    if (href === "/") {
      return pathname === "/"
    }
    return pathname.startsWith(href)
  }

  return (
    <nav className="fixed top-0 left-0 right-0 z-50 bg-white/95 backdrop-blur border-b border-border">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between items-center h-16">
          {/* Logo / Brand */}
          <Link
            href="/"
            className="flex items-center gap-3 text-primary hover:opacity-90 transition-opacity"
          >
            {/* The second half carries the highlighter mark a results page
                puts on a matched word. */}
            <span className="font-display text-xl font-bold tracking-tight">
              {logoPrefix}
              <mark className="ml-0.5 bg-accent text-primary rounded-sm px-1">{logoAccent}</mark>
            </span>
          </Link>

          {/* Desktop Navigation */}
          <div className="hidden md:flex items-center gap-8">
            {items.map((item) => {
              const active = isActive(item.href)
              const isChat = item.href === "/chat"

              if (isChat) {
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className="font-medium text-sm px-5 py-2 bg-brand text-white rounded-full hover:bg-brand-dark transition-colors cursor-pointer"
                  >
                    Start Chat
                  </Link>
                )
              }

              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`
                    font-medium text-sm transition-colors cursor-pointer
                    ${active
                      ? "text-brand underline decoration-2 underline-offset-[22px]"
                      : "text-muted-foreground hover:text-primary"
                    }
                  `}
                >
                  {item.label}
                </Link>
              )
            })}
            <AuthStatus />
          </div>

          {/* Mobile Navigation Button */}
          <div className="md:hidden">
            <button
              onClick={() => setIsMenuOpen(!isMenuOpen)}
              className="p-2 text-muted-foreground hover:text-primary transition-colors cursor-pointer"
              aria-label="Toggle menu"
            >
              {isMenuOpen ? <X size={24} /> : <Menu size={24} />}
            </button>
          </div>
        </div>

        {/* Mobile Navigation Menu */}
        {isMenuOpen && (
          <div className="md:hidden border-t border-border">
            <div className="py-4 space-y-2">
              {items.map((item) => {
                const active = isActive(item.href)
                const isChat = item.href === "/chat"

                if (isChat) {
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      className="block font-medium text-base py-3 px-4 bg-brand text-white text-center rounded-full mx-4 cursor-pointer"
                      onClick={() => setIsMenuOpen(false)}
                    >
                      Start Chat
                    </Link>
                  )
                }

                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`
                      block font-medium text-base py-3 px-4 transition-colors cursor-pointer
                      ${active
                        ? "text-brand"
                        : "text-muted-foreground hover:text-primary"
                      }
                    `}
                    onClick={() => setIsMenuOpen(false)}
                  >
                    {item.label}
                  </Link>
                )
              })}
              <AuthStatus className="px-4 py-3" />
            </div>
          </div>
        )}
      </div>
    </nav>
  )
}
