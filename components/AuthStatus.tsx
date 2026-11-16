"use client"

import { useAuth } from "@/hooks/use-auth"

/**
 * Sign in / sign out in the top bar. Renders nothing while loading, and
 * nothing at all when sign-in is off (local development). Plain links, not
 * fetches: each route answers with a redirect the browser has to follow.
 */
export function AuthStatus({ className = "" }: { className?: string }) {
  const auth = useAuth()
  if (auth.loading || !auth.enabled) return null
  if (!auth.signedIn) {
    return (
      <a href="/api/auth/login" className={`font-medium text-sm text-muted-foreground hover:text-primary transition-colors ${className}`}>
        Sign in
      </a>
    )
  }
  return (
    <span className={`flex items-center gap-3 text-sm ${className}`}>
      {auth.email && <span className="text-muted-foreground truncate max-w-[12rem]">{auth.email}</span>}
      <a href="/api/auth/logout" className="font-medium text-muted-foreground hover:text-primary transition-colors">
        Sign out
      </a>
    </span>
  )
}
