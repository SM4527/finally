import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";

const config: NextConfig = isDev
  ? {
      async rewrites() {
        return [{ source: "/api/:path*", destination: "http://localhost:8000/api/:path*" }];
      },
    }
  : { output: "export", images: { unoptimized: true } };

export default config;
