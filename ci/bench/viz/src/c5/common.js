import { rng } from "../harness.js";
/** A process display: `n` symbols (tanks with a level, valves with a state, pumps) on a 20-column
 * grid, each with a live value label, joined by lines; and a feed that changes every value. */
export function display(n = 300) {
  const items = [];
  for (let i = 0; i < n; i++) items.push({ id: i, kind: ["tank", "valve", "pump"][i % 3], x: 30 + (i % 20) * 62, y: 30 + Math.floor(i / 20) * 50, value: 50, level: 0.5, on: true });
  const lines = [];
  for (let i = 0; i < n - 1; i++) if ((i + 1) % 20) lines.push([i, i + 1]);
  const r = rng(9);
  const feed = () => { for (const it of items) { it.value = +(it.value + (r() - 0.5) * 2).toFixed(1); it.level = Math.max(0, Math.min(1, it.level + (r() - 0.5) * 0.05)); if (r() < 0.02) it.on = !it.on; } };
  return { items, lines, feed };
}
export const STRESS_MS = 3000;
