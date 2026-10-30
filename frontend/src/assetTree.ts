/** How far the asset tree opens: "Open to level N" shows the installation and N
 * levels under it, so level 1 lists the installation's units and level 2 what each unit holds. A
 * person's choice is kept in this browser; opening a folder by hand works as before. */

export const TREE_LEVELS = [1, 2, 3] as const;
export const DEFAULT_TREE_LEVEL = 2;
export const ALL_LEVELS = 99;
const KEY = "processcraft:assets:tree-level";

type Node = { asset_id: string };

/** The folders to open so the tree shows `level` levels under its tops (the installation). */
export function openToLevel(tree: Map<string | null, Node[]>, level: number): Set<string> {
  const open = new Set<string>();
  let row = tree.get(null) ?? [];
  for (let depth = 0; depth < level && row.length; depth += 1) {
    const next: Node[] = [];
    for (const item of row) {
      const kids = tree.get(item.asset_id) ?? [];
      if (kids.length) { open.add(item.asset_id); next.push(...kids); }
    }
    row = next;
  }
  return open;
}

export function savedTreeLevel(): number {
  try {
    const value = Number(window.localStorage.getItem(KEY));
    return value === ALL_LEVELS || (TREE_LEVELS as readonly number[]).includes(value) ? value : DEFAULT_TREE_LEVEL;
  } catch {
    return DEFAULT_TREE_LEVEL;
  }
}

export function saveTreeLevel(level: number): void {
  try { window.localStorage.setItem(KEY, String(level)); } catch { /* private window: the default next time */ }
}
