// Rebuilds one app's interface on every change of its source (dev/README.md).
//
//   node <processcraft>/dev/watch.mjs [--once] [--ui <processcraft>/ui/src]
//
// Run it in the app's frontend folder. It is the app's own `vite build` (its vite.config, its
// base path, its output folder dist/), changed for speed: it keeps watching and rebuilds only
// what changed, it does not minify, it never empties dist/ (the running app serves from it, and
// the hashed names of a new build never collide with the old ones), and Plotly, already built,
// is loaded as it is instead of being bundled again on every change. Its pages reload by
// themselves when a new build lands. With --ui, @plantcraft/ui comes from the shared package's
// source instead of the vendored file, so a change to the suite frame shows in every app at once.
// Never used for a release: `make image` builds the interface the normal way.
import { createRequire } from "node:module";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const args = process.argv.slice(2);
const once = args.includes("--once");
const uiAt = args.indexOf("--ui");
const ui = uiAt >= 0 ? path.resolve(args[uiAt + 1] ?? "") : "";
const root = process.cwd();
const require = createRequire(path.join(root, "package.json"));

// Vite from the app's own node_modules, so the build is the one its package-lock pins.
const vite = await import(pathToFileURL(require.resolve("vite")).href);

const resolve = {};
if (ui) {
  if (!existsSync(path.join(ui, "index.ts"))) throw new Error(`--ui ${ui}: no index.ts there`);
  resolve.alias = [
    { find: /^@processcraft\/ui$/, replacement: path.join(ui, "index.ts") },
    { find: /^@processcraft\/ui\/appMarks$/, replacement: path.join(ui, "appMarks.ts") },
    { find: /^@processcraft\/ui\/(.+\.css)$/, replacement: path.join(ui, "$1") },
  ];
  // The shared source sits outside this app and has no node_modules of its own: its imports
  // (React, the icons, the fonts) resolve to this app's copies, so there is one React.
  resolve.dedupe = ["react", "react-dom", "lucide-react", "@fontsource/ibm-plex-sans", "@fontsource/ibm-plex-mono"];
}

const PLOTLY = "plotly.js-cartesian-dist-min";
const PLOTLY_FILE = "static/plotly-quick.min.js";

/** Plotly's minified bundle as a classic script (window.Plotly), out of every rebuild. */
function plotlyAsIs() {
  let bundle = null;
  try {
    bundle = require.resolve(PLOTLY);
  } catch {
    return null; // the app does not draw charts
  }
  let emitted = false;
  let base = "/";
  return {
    name: "quick-plotly",
    enforce: "pre",
    configResolved: (config) => void (base = config.base),
    resolveId: (id) => (id === PLOTLY ? "\0quick-plotly" : null),
    load: (id) => (id === "\0quick-plotly" ? "export default window.Plotly;" : null),
    generateBundle() {
      if (emitted && existsSync(path.join(root, "dist", PLOTLY_FILE))) return;
      this.emitFile({ type: "asset", fileName: PLOTLY_FILE, source: readFileSync(bundle) });
      emitted = true;
    },
    // After Vite's own HTML step, which would try to bundle a classic script.
    transformIndexHtml: {
      order: "post",
      handler: () => [{ tag: "script", attrs: { src: base + PLOTLY_FILE }, injectTo: "head-prepend" }],
    },
  };
}

/** A page of this build reloads itself when index.html changes (a newer build is served). */
function reloadOnNewBuild() {
  let base = "/";
  return {
    name: "quick-reload",
    configResolved: (config) => void (base = config.base),
    transformIndexHtml: {
      order: "post",
      handler: () => [
      {
        tag: "script",
        injectTo: "head",
        children:
          `(function(){var u=${JSON.stringify(base + "index.html")},last=null;` +
          `setInterval(function(){if(document.hidden)return;fetch(u,{cache:"no-store"})` +
          `.then(function(r){return r.ok?r.text():null}).then(function(t){if(!t)return;` +
          `if(last!==null&&t!==last)location.reload();last=t}).catch(function(){})},1500)})();`,
      },
    ],
    },
  };
}

const watcher = await vite.build({
  root,
  resolve,
  logLevel: "warn",
  plugins: [plotlyAsIs(), reloadOnNewBuild()].filter(Boolean),
  build: {
    minify: false,
    emptyOutDir: false,
    reportCompressedSize: false,
    // Polling, not file events: a checkout replaces files (events stop after the first one) and
    // the Mac's file sharing drops events. The installed packages change only with npm ci, which
    // restarts this build.
    watch: once ? null : { exclude: ["**/node_modules/**"], chokidar: { usePolling: true, interval: 250 } },
  },
});

if (!once) {
  let started = 0;
  watcher.on("event", (event) => {
    if (event.code === "START") started = Date.now();
    if (event.code === "END") console.log(`built in ${((Date.now() - started) / 1000).toFixed(1)} s`);
    if (event.code === "ERROR") console.error(`build failed: ${event.error?.message ?? event.error}`);
    if (event.result) event.result.close();
  });
}
