/** What the Algorithms pages and the editor window share: finding an algorithm, naming a copy,
 * the editor's own window and what a run's blocks said, as the editor draws it. */
import { frameOff } from "@plantcraft/ui";
import type { BlockCatalog, DiagramTrace } from "@plantcraft/ui/blockEditor";
import { t } from "./i18n";
import { href } from "./nav";
import type { Algorithm, BlockResult } from "./types";

/** The system algorithm every signal goes through. */
export const SIGNAL_QUALITY = "signal_quality";

/** The algorithm an id names: its own, or a 0.2 protocol id it replaced (``aliases``). */
export function algorithmOf<T extends Pick<Algorithm, "algorithm_id"> & { aliases?: string[] }>(items: T[], id: string | null | undefined): T | undefined {
  if (!id) return undefined;
  return items.find((item) => item.algorithm_id === id) ?? items.find((item) => item.aliases?.includes(id));
}

/** An id from a name, free among the ids taken ("Valve health (copy)" -> "valve_health_copy"). */
export function newAlgorithmId(name: string, taken: string[]): string {
  const base = name.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 60) || "algorithm";
  const used = new Set(taken);
  if (!used.has(base)) return base;
  let index = 2;
  while (used.has(`${base}_${index}`)) index += 1;
  return `${base}_${index}`;
}

/** The name a duplicate starts with. */
export function copyName(name: string): string {
  return t("{name} (copy)", { name });
}

/**
 * The editor's address: an algorithm, or a new one (from another, when ``from`` is given; around a
 * published model, when ``model`` is).
 */
export function editorPath(id: string | null, from?: string, model?: string): string {
  if (id) return `/editor/${encodeURIComponent(id)}`;
  if (model) return `/editor/new?model=${encodeURIComponent(model)}`;
  return from ? `/editor/new?from=${encodeURIComponent(from)}` : "/editor/new";
}

/**
 * The editor opens in its own window (like Simulink, the diagram has the whole
 * screen); one window per algorithm, brought forward when it is already open.
 */
export function openEditor(id: string | null, from?: string, model?: string): void {
  const name = id ? `linkcraft-editor-${id}` : `linkcraft-editor-new-${Date.now()}`;
  // Straight to the editor's own page: through the suite's frame it waited for an app that never
  // says it is ready (the editor has no sidebar), and in the public demo it never opened.
  const opened = window.open(frameOff(href(editorPath(id, from, model))), name);
  opened?.focus();
}

/** Saves in an editor window tell the other pages of Link to read the algorithms again. */
export const EDITOR_CHANNEL = "linkcraft-algorithms";

export function announceSaved(id: string): void {
  try {
    const channel = new BroadcastChannel(EDITOR_CHANNEL);
    channel.postMessage({ saved: id });
    channel.close();
  } catch {
    // An old browser: the other pages read again when they are opened.
  }
}

export function onSaved(listener: (id: string) => void): () => void {
  try {
    const channel = new BroadcastChannel(EDITOR_CHANNEL);
    channel.onmessage = (event: MessageEvent<{ saved?: string }>) => { if (event.data?.saved) listener(event.data.saved); };
    return () => channel.close();
  } catch {
    return () => undefined;
  }
}

/** What each block said in a run (``summary.blocks``), on its verdict outputs, as a test trace. */
export function traceOfBlocks(catalog: BlockCatalog, nodes: Array<{ id: string; block: string }>, blocks: Record<string, BlockResult> | undefined): DiagramTrace {
  const trace: DiagramTrace = {};
  if (!blocks) return trace;
  const specs = Object.fromEntries(catalog.blocks.map((block) => [block.block_id, block]));
  for (const node of nodes) {
    const said = blocks[node.id];
    const port = specs[node.block]?.outputs.find((item) => item.type === "result");
    if (!said || !port) continue;
    trace[node.id] = { [port.port]: { type: "result", status: said.status, value: said.value, message: said.message } };
  }
  return trace;
}

/** How many blocks of each library a diagram uses, for a card ("3 data quality · 5 loop performance"). */
export function contents(catalog: BlockCatalog, nodes: Array<{ block: string }>): string {
  const names = Object.fromEntries(catalog.libraries.map((item) => [item.library, item.name]));
  const counts = new Map<string, number>();
  for (const node of nodes) {
    const library = node.block.split(".")[0];
    if (library === "input" || library === "output") continue;
    counts.set(library, (counts.get(library) ?? 0) + 1);
  }
  return [...counts].map(([library, count]) => `${count} ${(names[library] ?? library).toLowerCase()}`).join(" · ");
}

/** The tags of every algorithm, each with how many carry it, by name. */
export function tagOptions(items: Pick<Algorithm, "tags">[]): Array<{ id: string; label: string; count: number }> {
  const counts = new Map<string, number>();
  for (const item of items) for (const tag of item.tags ?? []) counts.set(tag, (counts.get(tag) ?? 0) + 1);
  return [...counts].sort((a, b) => a[0].localeCompare(b[0])).map(([tag, count]) => ({ id: tag, label: tag, count }));
}

/** The algorithms carrying any of the tags ticked (none ticked: all). */
export function withTags<Row extends Pick<Algorithm, "tags">>(items: Row[], tags: string[]): Row[] {
  return tags.length ? items.filter((item) => (item.tags ?? []).some((tag) => tags.includes(tag))) : items;
}
