/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { sharedVendor } from "./sharedVendor.mjs";
import { sharedWithUi } from "@plantcraft/ui/vite";

export default defineConfig({
  plugins: [react(), sharedVendor()],
  // @plantcraft/ui is linked from this repository's ui/ (file:../ui): one copy of each
  // library both use, this folder's.
  resolve: { dedupe: sharedWithUi(new URL(".", import.meta.url)) },
  build: {
    outDir: "dist",
    // Built files live under /static/; /assets/<id> is the asset deep link (docs/app-standard.md).
    assetsDir: "static",
    sourcemap: false,
    // Plotly alone is ~1.4 MB; it sits in its own chunk so it stays cached across releases.
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom"],
          icons: ["lucide-react"],
          plotly: ["plotly.js-cartesian-dist-min"],
        },
      },
    },
  },
  // Unit tests load @plantcraft/ui through Vite: its build uses bundler-style imports.
  test: { server: { deps: { inline: ["@plantcraft/ui"] } } },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8061",
      "/healthz": "http://127.0.0.1:8061",
    },
  },
});
