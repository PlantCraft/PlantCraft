// For the Vite config of an interface that draws @plantcraft/ui (PlantCraft's frontend and every
// app's). Plain JavaScript beside the package, not in dist/: a config runs under Node, before any
// build. In the PlantCraft repository the interfaces link ui/ itself (file:../ui), whose own
// node_modules hold a second React; `resolve.dedupe` sends the libraries both share to one copy.
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * The libraries @plantcraft/ui shares with the interface (its peer dependencies and react-dom)
 * that the interface has installed itself: Vite's `resolve.dedupe` for that interface.
 * @param {string | URL} root the interface's folder (`new URL(".", import.meta.url)` in its config)
 * @returns {string[]}
 */
export function sharedWithUi(root) {
  const folder = root instanceof URL ? fileURLToPath(root) : root;
  const own = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8"));
  const names = [...Object.keys(own.peerDependencies ?? {}), "react-dom"];
  return names.filter((name) => existsSync(join(folder, "node_modules", name)));
}
