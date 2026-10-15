/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const backend = process.env.MARKETOPS_BACKEND_URL ?? "http://127.0.0.1:8000";

// Development mirrors production's single-origin topology: the browser talks only to Vite,
// which proxies /api and the /ws upgrade to FastAPI, so session cookies stay first-party.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: Number(process.env.MARKETOPS_WEB_PORT ?? 5173),
    strictPort: true,
    proxy: {
      "/api": { target: backend, changeOrigin: false },
      "/ws": { target: backend.replace(/^http/, "ws"), ws: true, changeOrigin: false },
    },
  },
  // `vite preview` emulates the Vercel topology locally: /api is proxied (like the vercel.json
  // rewrite) while the WebSocket goes straight to the backend origin set in VITE_STREAM_URL.
  preview: {
    port: Number(process.env.MARKETOPS_WEB_PORT ?? 4173),
    strictPort: true,
    proxy: { "/api": { target: backend, changeOrigin: true } },
  },
  build: {
    sourcemap: true,
    chunkSizeWarningLimit: 1600,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
