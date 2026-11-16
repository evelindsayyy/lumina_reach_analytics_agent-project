import type React from "react"
import type { Metadata, Viewport } from "next"
import { Bricolage_Grotesque, IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google"
import { generateSEOMetadata } from "@/lib/seo/generateMetadata"
import { loadSite } from "@/lib/site/load"
import "./globals.css"

// The three faces of the results-page tone (see tailwind.config.ts).
const display = Bricolage_Grotesque({
  subsets: ["latin"],
  variable: "--font-display",
  weight: ["500", "600", "700"],
})
const body = IBM_Plex_Sans({
  subsets: ["latin"],
  variable: "--font-body",
  weight: ["400", "500", "600"],
})
const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  weight: ["400", "500"],
})

const { seo } = loadSite()

export const metadata: Metadata = {
  ...generateSEOMetadata({
    title: seo.title,
    description: seo.description,
  }),
  icons: {
    icon: [
      { url: '/icon.png', type: 'image/png' },
    ],
    shortcut: '/icon.png',
    apple: '/icon.png',
  },
}

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${mono.variable}`}>
      <body className={`${body.className} antialiased`}>{children}</body>
    </html>
  )
}
