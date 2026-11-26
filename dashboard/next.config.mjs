/** @type {import('next').NextConfig} */
// STATIC_EXPORT=1 builds plain files into ./out that the FastAPI app serves
// itself (single container, one origin: see the root Dockerfile). Every page is
// a client component, so nothing needs a Node server at runtime.
const staticExport = process.env.STATIC_EXPORT === "1";

const nextConfig = {
  reactStrictMode: true,
  // separate build dir so an export never clobbers a running `next dev`
  ...(staticExport ? { output: "export", trailingSlash: true, images: { unoptimized: true }, distDir: "out" } : {}),
};
export default nextConfig;
