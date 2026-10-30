/** Python in this browser (Notebooks › Run in the browser): PlantCraft serves each JupyterLite
 * build under a path of its own, kept by the browser for a year (plantcraft/notebooks/dist.py).
 * "Install" fetches every file of the build once, with its progress, so JupyterLab and Python
 * then open from this computer; "installed" is remembered per build and checked against the
 * browser's cache, which can drop files when the disk runs short. */

const KEY = "plantcraft-notebooks-installed";
// Files fetched at once while installing.
const PARALLEL = 4;

export type BrowserFiles = { build: string; bytes: number; files: string[] };

function remembered(): string {
  try { return window.localStorage.getItem(KEY) ?? ""; } catch { return ""; }
}

function remember(build: string | null) {
  try {
    if (build) window.localStorage.setItem(KEY, build); else window.localStorage.removeItem(KEY);
  } catch { /* private window: installing again is the price */ }
}

/** The files whose presence says Python is still here: the engine and the biggest packages. */
export function probes(files: string[]): string[] {
  const wanted = [/pyodide\.asm\.wasm$/, /\/pandas-[^/]*\.(whl|zip)$/, /\/scipy-[^/]*\.(whl|zip)$/];
  return wanted.map((pattern) => files.find((file) => pattern.test(file))).filter((file): file is string => Boolean(file));
}

/** True when this build was installed here and its main files are still in the browser's cache. */
export async function installed(listing: BrowserFiles): Promise<boolean> {
  if (remembered() !== listing.build) return false;
  for (const url of probes(listing.files)) {
    try {
      const answer = await fetch(url, { cache: "only-if-cached", mode: "same-origin" });
      if (!answer.ok) return false;
      // Only the headers were needed: the body stays in the cache.
      await answer.body?.cancel();
    } catch {
      // A miss is an answer (504); an error means this browser cannot ask its cache this way:
      // then what was remembered stands.
      return true;
    }
  }
  return true;
}

/** Fetches every file once into the browser's cache; ``onProgress`` gets the bytes so far. */
export async function install(listing: BrowserFiles, onProgress: (bytes: number) => void, signal?: AbortSignal): Promise<void> {
  // Ask the browser to keep this site's storage (the person's notebooks) when space runs short.
  void navigator.storage?.persist?.().catch(() => false);
  let done = 0;
  const queue = [...listing.files];
  async function worker() {
    for (let url = queue.shift(); url; url = queue.shift()) {
      const answer = await fetch(url, { signal, credentials: "same-origin" });
      if (!answer.ok) throw new Error(`${answer.status} ${url}`);
      const reader = answer.body?.getReader();
      if (!reader) { done += Number(answer.headers.get("content-length") ?? 0); onProgress(done); continue; }
      for (;;) {
        const { value, done: finished } = await reader.read();
        if (finished) break;
        done += value.byteLength;
        onProgress(done);
      }
    }
  }
  await Promise.all(Array.from({ length: PARALLEL }, worker));
  remember(listing.build);
}

/** Forgets the installation here: the next visit installs again (the browser drops the files
 * from its cache when it needs the space). */
export function forget() {
  remember(null);
}

export function megabytes(bytes: number): string {
  return `${Math.round(bytes / 1_000_000)} MB`;
}
