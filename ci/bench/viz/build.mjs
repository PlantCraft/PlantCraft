// Bundles every case in src/<item>/<library>.{js,jsx} to dist/<item>-<library>.js (minified),
// and writes dist/sizes.json: what each case adds to a page, raw and gzipped.
import { build } from "esbuild";
import { readdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { gzipSync } from "node:zlib";
import path from "node:path";

const only = process.argv[2];
const entries = {};
for (const item of readdirSync("src", { withFileTypes: true })) {
  if (!item.isDirectory() || (only && !item.name.startsWith(only))) continue;
  for (const file of readdirSync(path.join("src", item.name))) {
    if (!/\.(js|jsx|tsx)$/.test(file) || file.startsWith("common")) continue;
    entries[`${item.name}-${file.replace(/\.(js|jsx|tsx)$/, "")}`] = path.join("src", item.name, file);
  }
}
const sizes = existsSync("dist/sizes.json") ? JSON.parse(readFileSync("dist/sizes.json", "utf8")) : {};
for (const [name, entry] of Object.entries(entries)) {
  try {
  await build({
    entryPoints: { [name]: entry }, outdir: "dist", bundle: true, minify: true, format: "esm", target: "es2022",
    jsx: "automatic", define: { "process.env.NODE_ENV": '"production"', global: "globalThis" },
    loader: { ".ttf": "file", ".woff": "file", ".woff2": "file", ".png": "dataurl", ".svg": "dataurl" },
    nodePaths: [path.resolve("node_modules")], logLevel: "error",
  });
  let raw = 0, gz = 0;
  for (const ext of [".js", ".css"]) {
    const file = `dist/${name}${ext}`;
    if (!existsSync(file)) continue;
    const body = readFileSync(file);
    raw += body.length; gz += gzipSync(body, { level: 9 }).length;
  }
  sizes[name] = { kb: Math.round(raw / 1024), kb_gzip: Math.round(gz / 1024) };
  console.log(name, sizes[name]);
  } catch (e) { console.log("FAILED", name, String(e).slice(0, 600)); }
}
writeFileSync("dist/sizes.json", JSON.stringify(sizes, null, 1));
