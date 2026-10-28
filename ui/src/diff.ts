/** Line differences between two texts, for comparing versions of code (Link's blocks, Models'
 * blocks and models): the longest common subsequence, as `git diff` shows it. */

export type DiffLine = { kind: "same" | "added" | "removed"; text: string; before?: number; after?: number };

/** The lines that changed from `before` to `after` (longest common subsequence). */
export function lineDiff(before: string, after: string): DiffLine[] {
  const a = before.split("\n");
  const b = after.split("\n");
  // Too long to compare line by line in the page: show both as replaced.
  if (a.length * b.length > 4_000_000) {
    return [...a.map((text, index) => ({ kind: "removed" as const, text, before: index + 1 })), ...b.map((text, index) => ({ kind: "added" as const, text, after: index + 1 }))];
  }
  const rows = a.length + 1;
  const columns = b.length + 1;
  const table = new Uint32Array(rows * columns);
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      table[i * columns + j] = a[i] === b[j] ? table[(i + 1) * columns + j + 1] + 1 : Math.max(table[(i + 1) * columns + j], table[i * columns + j + 1]);
    }
  }
  const found: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) { found.push({ kind: "same", text: a[i], before: i + 1, after: j + 1 }); i += 1; j += 1; }
    else if (table[(i + 1) * columns + j] >= table[i * columns + j + 1]) { found.push({ kind: "removed", text: a[i], before: i + 1 }); i += 1; }
    else { found.push({ kind: "added", text: b[j], after: j + 1 }); j += 1; }
  }
  while (i < a.length) { found.push({ kind: "removed", text: a[i], before: i + 1 }); i += 1; }
  while (j < b.length) { found.push({ kind: "added", text: b[j], after: j + 1 }); j += 1; }
  return found;
}
