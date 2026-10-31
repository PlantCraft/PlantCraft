import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Analytics is served under /link/ behind the suite's proxy (PlantCraft owns /).
export default defineConfig({
  base: "/link/",
  plugins: [react()],
  build: {
    outDir: "dist",
    // <prefix>assets/<id> is the asset deep link of the app standard; built files go to static/.
    assetsDir: "static",
    sourcemap: false,
    // Plotly alone is ~1.4 MB; it sits in its own chunk so it stays cached across releases. The
    // pages load lazily (App.tsx): the diagram and code editors split off with the pages using them.
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
    port: 5174,
    proxy: { "/link/api": "http://127.0.0.1:8140", "/link/healthz": "http://127.0.0.1:8140" },
  },
  // Vitest 5 no longer derives import.meta.env.BASE_URL from `base` in tests.
  test: { environment: "jsdom", env: { BASE_URL: "/link/" } },
});
