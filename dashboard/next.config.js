/** @type {import('next').NextConfig} */
const nextConfig = {
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
