/** @type {import('next').NextConfig} */
function agentApiUrl() {
  let url = (process.env.AGENT_API_URL || "http://localhost:8000").trim();
  url = url.replace(/\/+$/, "");                       // strip trailing slashes
  if (!/^https?:\/\//i.test(url)) url = "https://" + url; // tolerate missing scheme
  return url;
}

const nextConfig = {
  async rewrites() {
    return [{ source: "/agent/:path*", destination: `${agentApiUrl()}/:path*` }];
  },
};
module.exports = nextConfig;
