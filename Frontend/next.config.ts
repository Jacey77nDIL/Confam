import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Manual PWA (public/sw.js) keeps Turbopack dev stable; avoid bundling heavy SW plugins here.
};

export default nextConfig;
