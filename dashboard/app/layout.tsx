import type { Metadata } from "next";
import { Archivo, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import { Nav } from "@/components/Nav";
import { Footer } from "@/components/Footer";
import { BackgroundGlow } from "@/components/BackgroundGlow";

// Two type families only, per docs/BRANDING.md §4 — an earlier brand draft
// used four and it read as inconsistent. Archivo carries body/UI/headlines;
// IBM Plex Mono carries every number and data label (applied via the
// `.mono` class in globals.css, not globally).
const archivo = Archivo({
  subsets: ["latin"],
  weight: ["400", "500", "600", "800", "900"],
  variable: "--font-body",
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Isogram — the data truth layer for Arc",
  description:
    "USDC gas/flow analytics, TVL, and the Arc Native Score — live from Arc mainnet, read directly via RPC.",
  // Per docs/BRANDING.md §2.3: 🔺 is the designated emoji fallback for
  // contexts that only support an emoji favicon, ahead of a rendered
  // multi-size favicon.ico from brand-assets/ being wired in.
  icons: {
    icon: "data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🔺</text></svg>",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${archivo.variable} ${plexMono.variable}`}>
      <body>
        <BackgroundGlow />
        <Nav />
        {children}
        <Footer />
      </body>
    </html>
  );
}
