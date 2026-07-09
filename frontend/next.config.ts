import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  turbopack: {
    // An unrelated, pre-existing package-lock.json in the user's home
    // directory (outside this project) was causing Turbopack to misdetect
    // the workspace root. Pin it explicitly.
    root: path.join(__dirname),
  },
};

export default nextConfig;
