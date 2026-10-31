import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Historian is served under /hist/ behind the suite's proxy (PlantCraft owns /).
export default defineConfig({
  base: "/hist/",
  plugins: [react()],
  build: {
    outDir: "dist",
    // assets/ is reserved for asset deep links (PlantCraft app standard, section 7).
    assetsDir: "static",
    sourcemap: false,
    // Plotly alone is ~1.4 MB; it sits in its own chunk so it stays cached across releases.
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        manualChunks: {
          icons: ["lucide-react"],
          plotly: ["plotly.js-cartesian-dist-min"],
        },
      },
    },
  },
  server: {
    port: 5175,
    proxy: { "/hist/api": "http://127.0.0.1:8100", "/hist/healthz": "http://127.0.0.1:8100" },
  },
  // Vitest 5 no longer derives import.meta.env.BASE_URL from `base` in tests.
  test: { environment: "jsdom", env: { BASE_URL: "/hist/" } },
});
