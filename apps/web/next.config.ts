import type { NextConfig } from "next";
import { existsSync } from "node:fs";
import path from "node:path";
import { loadEnvFile } from "node:process";

const repositoryRoot = path.resolve(import.meta.dirname, "../..");
const repositoryEnv = path.join(repositoryRoot, ".env");
if (existsSync(repositoryEnv)) {
  loadEnvFile(repositoryEnv);
}

const nextConfig: NextConfig = {
  output: "standalone",
  outputFileTracingRoot: repositoryRoot,
  turbopack: {
    root: repositoryRoot,
  },
};

export default nextConfig;
