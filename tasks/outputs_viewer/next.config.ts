import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Data + feedback files live outside this app dir (repo-root data/); the
  // server code reads them with fs at request time, nothing to configure.
  // Keep the client bundle free of any env secrets: only server modules
  // import src/lib/server/*.
  reactStrictMode: true,
};

export default nextConfig;
