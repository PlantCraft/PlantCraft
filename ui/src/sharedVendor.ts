/**
 * Files the platform serves once for the whole suite, at /static/vendor/, so a visit through
 * several apps downloads them once instead of once per app (each app has its own /<app>/static/).
 * Each name carries the first 10 hex digits of the file's SHA-256: the proxy keeps /static/* a
 * year (immutable), and a file that changes gets a new name. The platform's build copies the
 * files under these names only when their bytes give the same hash (frontend/vite.config.ts);
 * otherwise the name answers 404 and every user of these files falls back to the app's own copy
 * (the Plotly import in Plot.tsx, the second `src` of each @font-face in fonts.css).
 *
 * After a Plotly upgrade or a new font file, `node ui/scripts/shared-vendor-names.mjs` prints the
 * new names; sharedVendor.test.ts fails until they are updated here and in fonts.css.
 */
export const SHARED_VENDOR_URL = "/static/vendor/";

export interface SharedFile {
  /** The npm package the file comes from. */
  package: string;
  /** Its path inside that package. */
  file: string;
  /** The name served under SHARED_VENDOR_URL. */
  name: string;
}

export const SHARED_PLOTLY: SharedFile = {
  package: "plotly.js-cartesian-dist-min",
  file: "plotly-cartesian.min.js",
  name: "plotly-cartesian-7c593b9eda.min.js",
};

export const SHARED_FONTS: SharedFile[] = [
  { package: "@plantcraft/ui", file: "dist/fonts/inter-latin-opsz-normal.woff2", name: "fonts/inter-latin-opsz-normal-2c295d99e2.woff2" },
  { package: "@plantcraft/ui", file: "dist/fonts/inter-latin-opsz-italic.woff2", name: "fonts/inter-latin-opsz-italic-c58f9d530b.woff2" },
  { package: "@plantcraft/ui", file: "dist/fonts/jetbrains-mono-latin-400-normal.woff2", name: "fonts/jetbrains-mono-latin-400-normal-14425ba9c6.woff2" },
  { package: "@plantcraft/ui", file: "dist/fonts/jetbrains-mono-latin-500-normal.woff2", name: "fonts/jetbrains-mono-latin-500-normal-cb182feeed.woff2" },
];

export const SHARED_FILES: SharedFile[] = [SHARED_PLOTLY, ...SHARED_FONTS];

/** The hashed name of `file` given its bytes' SHA-256 in hex: "plotly-cartesian.min.js" -> "plotly-cartesian-<10 hex>.min.js". */
export function sharedName(file: string, sha256: string): string {
  const base = file.split("/").pop() ?? file;
  const dot = base.indexOf(".");
  const stem = dot < 0 ? base : base.slice(0, dot);
  const ext = dot < 0 ? "" : base.slice(dot);
  return `${stem}-${sha256.slice(0, 10)}${ext}`;
}
