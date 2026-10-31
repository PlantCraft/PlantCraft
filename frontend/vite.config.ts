/// <reference types="vitest/config" />
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { SHARED_FILES, SHARED_VENDOR_URL, sharedName } from "@plantcraft/ui/sharedVendor";

/**
 * The files every app asks of the platform first (Plotly, the fonts: @plantcraft/ui's
 * sharedVendor.ts), emitted under static/vendor/ with the hashed name the ui expects. A file
 * whose bytes give another hash (another Plotly here than in the ui) is left out: its name then
 * answers 404 and each app uses its own copy, as before.
 */
function sharedVendor(): Plugin {
  const require = createRequire(import.meta.url);
  return {
    name: "plantcraft-shared-vendor",
    apply: "build",
    generateBundle() {
      for (const file of SHARED_FILES) {
        const root = dirname(require.resolve(`${file.package}/package.json`));
        const bytes = readFileSync(join(root, file.file));
        const name = sharedName(file.file, createHash("sha256").update(bytes).digest("hex"));
        if (name !== file.name.split("/").pop()) {
          this.warn(`${file.package}/${file.file} is not the build the ui names (${file.name}): apps will use their own copy`);
          continue;
        }
        this.emitFile({ type: "asset", fileName: `${SHARED_VENDOR_URL.replace(/^\//, "")}${file.name}`, source: bytes });
      }
    },
  };
}

export default defineConfig({
  plugins: [react(), sharedVendor()],
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
