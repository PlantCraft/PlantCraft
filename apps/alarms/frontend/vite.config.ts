import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// PlantCraft Alarms is served under /alarm/ behind the suite's proxy (PlantCraft owns /).
export default defineConfig({
  base: "/alarm/",
  plugins: [react()],
  build: {
    outDir: "dist",
    // Not "assets": <prefix>assets/<id> is the suite's uniform page for one asset.
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
    port: 5177,
    proxy: { "/alarm/api": "http://127.0.0.1:8110", "/alarm/healthz": "http://127.0.0.1:8110" },
  },
  // Vitest 5 no longer derives import.meta.env.BASE_URL from `base` in tests.
  test: { environment: "jsdom", env: { BASE_URL: "/alarm/" } },
});
