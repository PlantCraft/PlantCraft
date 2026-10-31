/** The block palette, shared by the pages; kept apart from the editor so a page that only reads it does not load React Flow. */
import { api } from "./api";
import type { Blocks } from "./types";

let blocksCache: Promise<Blocks> | null = null;
/** The palette, read once per page load (again after a block is saved). */
export function blockCatalog(): Promise<Blocks> {
  if (!blocksCache) blocksCache = api.blocks().catch((error: unknown) => { blocksCache = null; throw error; });
  return blocksCache;
}

/** Read the palette again on next use: a block was saved, copied or deleted. */
export function forgetBlockCatalog(): void {
  blocksCache = null;
}
