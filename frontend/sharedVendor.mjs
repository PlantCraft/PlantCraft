// The platform's build step that emits the files every app asks of it first. Plain JavaScript:
// the build's type check (tsconfig.node.json) has no Node types.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { SHARED_FILES, SHARED_VENDOR_URL, sharedName } from "@plantcraft/ui/sharedVendor";

/**
 * The files every app asks of the platform first (Plotly, the fonts: @plantcraft/ui's
 * sharedVendor.ts), emitted under static/vendor/ with the hashed name the ui expects. A file
 * whose bytes give another hash (another Plotly here than in the ui) is left out: its name then
 * answers 404 and each app uses its own copy, as before.
 */
/** @returns {import("vite").Plugin} */
export function sharedVendor() {
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
