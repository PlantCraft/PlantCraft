/** A squarified treemap (Bruls, Huizing and van Wijk, 2000): rectangles whose areas are
 * proportional to their weights, laid out row by row so they stay close to squares. */

export interface Rect { x: number; y: number; w: number; h: number }
export interface Placed<T> extends Rect { item: T }

function worst(row: number[], side: number): number {
  const sum = row.reduce((a, b) => a + b, 0);
  const max = Math.max(...row), min = Math.min(...row);
  return Math.max((side * side * max) / (sum * sum), (sum * sum) / (side * side * min));
}

/** Lay out `items` (weights above 0, the rest skipped) inside `box`, largest first. */
export function squarify<T>(items: T[], weight: (item: T) => number, box: Rect): Placed<T>[] {
  const kept = items.map((item) => ({ item, w: weight(item) })).filter((entry) => entry.w > 0 && Number.isFinite(entry.w));
  const total = kept.reduce((sum, entry) => sum + entry.w, 0);
  if (!kept.length || box.w <= 0 || box.h <= 0) return [];
  const scale = (box.w * box.h) / total;
  const queue = kept.sort((a, b) => b.w - a.w).map((entry) => ({ item: entry.item, area: entry.w * scale }));
  const placed: Placed<T>[] = [];
  let free = { ...box };
  let row: typeof queue = [];
  const flush = () => {
    const sum = row.reduce((a, b) => a + b.area, 0);
    const wide = free.w >= free.h;
    const thick = sum / (wide ? free.h : free.w);
    let offset = 0;
    for (const entry of row) {
      const length = entry.area / thick;
      placed.push(wide
        ? { item: entry.item, x: free.x, y: free.y + offset, w: thick, h: length }
        : { item: entry.item, x: free.x + offset, y: free.y, w: length, h: thick });
      offset += length;
    }
    free = wide ? { x: free.x + thick, y: free.y, w: free.w - thick, h: free.h } : { x: free.x, y: free.y + thick, w: free.w, h: free.h - thick };
    row = [];
  };
  for (const entry of queue) {
    const side = Math.min(free.w, free.h);
    const areas = row.map((r) => r.area);
    if (row.length && worst([...areas, entry.area], side) > worst(areas, side)) flush();
    row.push(entry);
  }
  if (row.length) flush();
  return placed;
}
