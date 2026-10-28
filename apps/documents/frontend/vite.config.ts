import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// PlantCraft Documents is served under /doc/ behind the suite's proxy (PlantCraft owns /).
export default defineConfig({
  base: "/doc/",
  plugins: [react()],
  build: {
    outDir: "dist",
    // Not "assets": <prefix>assets/<id> is the suite's uniform page for one asset.
    assetsDir: "static",
    sourcemap: false,
    rollupOptions: { output: { manualChunks: { icons: ["lucide-react"] } } },
  },
  server: {
    port: 5177,
    proxy: { "/doc/api": "http://127.0.0.1:8150", "/doc/healthz": "http://127.0.0.1:8150" },
  },
  // Vitest 5 no longer derives import.meta.env.BASE_URL from `base` in tests.
  test: { environment: "jsdom", env: { BASE_URL: "/doc/" } },
});
