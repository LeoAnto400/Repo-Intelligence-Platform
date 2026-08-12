import path from "path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Pin the workspace root to this directory. Without this, Next.js walks
  // up the filesystem looking for lockfiles to infer a monorepo root and
  // picks up an unrelated package-lock.json in the user's home directory,
  // landing on the wrong root. That mismatch corrupts the dev server's file
  // tracing across restarts, which shows up as pages referencing hashed
  // build chunks (CSS/JS) that 404 — the page renders but is unstyled/broken.
  outputFileTracingRoot: path.join(__dirname),
  // Allow development requests when the app is opened through this LAN address.
  allowedDevOrigins: ["192.168.1.7"],
  // No rewrite proxy to the backend here on purpose: next dev's internal
  // proxy for external rewrite destinations has its own hardcoded timeout
  // (~20s) that a real repository ingest routinely exceeds, and tearing
  // down that connection crashes the whole dev server process. The
  // frontend calls the FastAPI backend directly instead (see api-client.ts).
};

export default nextConfig;
