/** @type {import('next').NextConfig} */
const nextConfig = {
  // Pin the workspace root to this repo. Without it, Turbopack picks the
  // directory of any lockfile it finds further up (a stray ~/package-lock.json
  // is enough), and next/font then fails to resolve in `next dev`.
  turbopack: {
    root: __dirname,
  },

  // Performance optimizations
  compiler: {
    // Strip console.log in production, but keep console.error / console.warn:
    // lib/agent-proxy.ts logs an unreachable agent runtime with them.
    removeConsole:
      process.env.NODE_ENV === 'production' ? { exclude: ['error', 'warn'] } : false,
  },

  // No `images.remotePatterns`: every image this app renders is local. Add the
  // host here if that ever stops being true.

  // No rewrites: the only backend call is app/api/chat/route.ts, which
  // forwards to the agent runtime (AGENT_RUNTIME_URL, else local port 8080).

  // Reduce bundle size
  productionBrowserSourceMaps: false,
};

module.exports = nextConfig;
