import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  turbopack: {
    // An unrelated, pre-existing package-lock.json in the user's home
    // directory (outside this project) was causing Turbopack to misdetect
    // the workspace root. Pin it explicitly.
    root: path.join(__dirname),
  },
  // Phase 10: traces the minimal set of files/deps a production server
  // actually needs into .next/standalone — the Docker image copies just
  // that output instead of the full node_modules tree.
  output: "standalone",
};

export default nextConfig;
