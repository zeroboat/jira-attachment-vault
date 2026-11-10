import path from "node:path";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "src") } },
  build: { chunkSizeWarningLimit: 800 },
  server: {
    port: 5173,
    // In dev, proxy API requests to FastAPI on :8000.
    proxy: { "/api": "http://localhost:8000" },
  },
});
