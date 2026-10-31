/** A block diagram: `n` blocks in columns of 10, each block feeding one or two blocks of the next column. */
export function blocks(n = 200) {
  const nodes = [], edges = [];
  for (let i = 0; i < n; i++) nodes.push({ id: `b${i}`, label: ["Signal", "Filter", "Lag", "PID check", "Oscillation", "Stiction"][i % 6] + ` ${i}`, x: 40 + Math.floor(i / 10) * 230, y: 30 + (i % 10) * 90 });
  for (let i = 0; i + 10 < n; i++) { edges.push([i, i + 10]); if (i % 3 === 0 && (i % 10) < 9) edges.push([i, i + 11]); }
  return { nodes, edges };
}
export const PAN_MS = 2000;
