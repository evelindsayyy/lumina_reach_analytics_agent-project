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
      <a href="/api/auth/login" className={`font-medium text-sm text-slate-300 hover:text-white transition-colors ${className}`}>
        Sign in
      </a>
    )
  }
  return (
    <span className={`flex items-center gap-3 text-sm ${className}`}>
      {auth.email && <span className="text-slate-400 truncate max-w-[12rem]">{auth.email}</span>}
      <a href="/api/auth/logout" className="font-medium text-slate-300 hover:text-white transition-colors">
        Sign out
      </a>
    </span>
  )
}
