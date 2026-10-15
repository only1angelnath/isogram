import type { Metadata } from "next";

// The admin desk is private: keep it out of search results (robots.txt already disallows crawling it).
export const metadata: Metadata = { title: "Admin", robots: { index: false, follow: false } };

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return children;
}
