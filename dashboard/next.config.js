/** @type {import('next').NextConfig} */
const nextConfig = {
  // The methodology page moved into the docs; keep old links and anchors working.
  async redirects() {
    return [{ source: "/methodology", destination: "/docs/methodology", permanent: true }];
  },
  // Badge SVGs are embedded via plain <img> tags pointing at the FastAPI
  // (see components/ScoreBadge.tsx) rather than next/image — they're
  // server-generated SVGs, not something Next's image optimizer adds value
  // to, and this avoids configuring a remote-image allowlist for what is,
  // for now, a single self-hosted API domain.
  images: {
    unoptimized: true,
  },
};

module.exports = nextConfig;
