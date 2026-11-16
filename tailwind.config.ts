import type { Config } from "tailwindcss"
import tailwindcssAnimate from "tailwindcss-animate"

// Tone: a search results page. The people this is for live in search engines
// and search term reports, so the app looks like the place their work starts:
// paper-white, crisp, quiet, with a search box as the front door.
//
//   mood        precise
//   ground      light: white, like a results page, never tinted
//   colours     ink #14171F for text; link indigo #2B3FD6, the colour of a
//               result you can click; highlighter yellow #FFE48A, the mark a
//               search engine puts on the words that matched your query; a
//               green-teal #1E6E5C for the result's display path
//   type        Bricolage Grotesque for the few display lines (condensed,
//               confident, used sparingly); IBM Plex Sans for reading; IBM
//               Plex Mono for queries, paths and numbers
//   layout      the home page is a results page: the question goes in the
//               search box, the four business threads come back as results,
//               the product facts sit in a knowledge panel beside them
//
// This app is light-only: there is no theme toggle, so no `darkMode` strategy
// and no `dark:` variants anywhere in the tree.
const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      /* The palette. Components name these instead of repeating a hex or a raw
       * Tailwind step, so a rebrand is this block and nothing else.
       *
       * Only the colours a rebrand actually changes live here. The neutral
       * scale stays as Tailwind's own `slate-*`: it is a vocabulary every React
       * developer already reads, and it survives a rebrand unchanged.
       *
       * Every value below is the exact hex of the Tailwind step it replaced, so
       * introducing these names changed no pixel. */
      colors: {
        /** Ink. Headings, body text on white, the user bubble, the wordmark. */
        primary: {
          DEFAULT: "#14171F",
          foreground: "#FFFFFF",
        },
        /** Link indigo: everything clickable, the send button, focus rings. */
        brand: {
          DEFAULT: "#2B3FD6",
          dark: "#1F2FB0", // hover on a filled surface
          light: "#4A5BE8", // focus rings
          soft: "#A9B2F5", // hover borders
          foreground: "#FFFFFF",
        },
        /** Highlighter yellow: the words that matched the query. A background,
         *  never a text colour: it is unreadable as ink on white. */
        accent: {
          DEFAULT: "#FFE48A",
          foreground: "#14171F",
        },
        /** A result's display path (lumina-reach › attribution-truth). */
        path: "#1E6E5C",
        /** Page and card backgrounds. */
        background: "#FFFFFF",
        foreground: "#14171F",
        surface: "#F6F7F9",
        border: "#E3E5EA", // what `@apply border-border` resolves to
        muted: {
          DEFAULT: "#EEF0F3",
          foreground: "#5F6573",
        },

        // shadcn/ui primitives. Kept whole because `components/ui/*` and any
        // component added with the shadcn CLI expect these exact names.
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
      },
      fontFamily: {
        display: ["var(--font-display)", "sans-serif"],
        heading: ["var(--font-display)", "sans-serif"],
        body: ["var(--font-body)", "sans-serif"],
        inter: ["var(--font-body)", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      /* Radius is a size ladder, and each step names a role:
       *
       *   rounded-full   pill        nav CTA, tech-stack tags
       *   rounded-2xl    panel       home CTA, agent welcome card, the modal
       *   rounded-xl     card        capability card, kickstart button, bubbles
       *   rounded-lg     block       code block, table, chart, avatars, buttons
       *   rounded-md/sm  inline      chart tooltip, legend swatches
       *
       * Nothing is extended here: these are Tailwind's own steps. There used to
       * be a shadcn override (`lg: var(--radius)` and two more derived from it)
       * which lifted `lg` from 8px to 12px -- the same value Tailwind already
       * gives `xl`. Two class names for one value is why the ladder read as
       * arbitrary in the components: half of the tree could pick either and
       * still look right. It also coupled our own scale to a variable set for
       * shadcn, so changing `--radius` would have split the design silently.
       * Nothing needed it: every shadcn `rounded-md` in `components/ui/*` is
       * overridden at its call site.
       */
    },
  },
  // an import, not require(): Node 24 loads this .ts file as an ES module
  plugins: [tailwindcssAnimate],
}

export default config
