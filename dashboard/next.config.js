/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    const api = process.env.AGENT_API_URL || "http://localhost:8000";
    return [{ source: "/agent/:path*", destination: `${api}/:path*` }];
  },
};
module.exports = nextConfig;
