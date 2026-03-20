import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

const backendTarget = process.env.VITE_SCHEDULER_API_TARGET || "http://127.0.0.1:27643";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    host: "0.0.0.0",
    port: 18766,
    proxy: {
      "/health": { target: backendTarget, changeOrigin: true },
      "/tasks": { target: backendTarget, changeOrigin: true },
      "/apps": { target: backendTarget, changeOrigin: true },
      "/runs": { target: backendTarget, changeOrigin: true },
      "/stats": { target: backendTarget, changeOrigin: true },
      "/api": { target: backendTarget, changeOrigin: true },
    },
  },
});
