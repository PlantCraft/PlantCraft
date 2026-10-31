// Print the hashed names of the files the platform serves once for the suite
// (ui/src/sharedVendor.ts). Run from the repository root after `npm ci` in ui/.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

const files = [
  "ui/node_modules/plotly.js-cartesian-dist-min/plotly-cartesian.min.js",
  "ui/src/fonts/inter-latin-opsz-normal.woff2",
  "ui/src/fonts/inter-latin-opsz-italic.woff2",
  "ui/src/fonts/jetbrains-mono-latin-400-normal.woff2",
  "ui/src/fonts/jetbrains-mono-latin-500-normal.woff2",
];
for (const path of files) {
  const sha = createHash("sha256").update(readFileSync(path)).digest("hex");
  const base = path.split("/").pop();
  const dot = base.indexOf(".");
  console.log(`${base.slice(0, dot)}-${sha.slice(0, 10)}${base.slice(dot)}`);
}
