/** @type {import('next').NextConfig} */
const nextConfig = {
  // Emit a minimal standalone server for a lean production Docker image.
  output: "standalone",
};

export default nextConfig;
