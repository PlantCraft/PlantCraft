// Today's way (View's DiagramCanvas): React draws the SVG, each element memoized, values passed as props.
import { memo, useState } from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import { main, root, timed, animate } from "../harness.js";
import { display, STRESS_MS } from "./common.js";
const Item = memo(function Item({ kind, x, y, value, level, on }) {
  return <g transform={`translate(${x} ${y})`}>
    {kind === "tank" && <><rect width={24} height={30} rx={4} fill="#f1f5f9" stroke="#334155" /><rect x={1} y={1 + 28 - 28 * level} width={22} height={28 * level} fill="#38bdf8" /></>}
    {kind === "valve" && <path d="M0 6 L24 18 L24 6 L0 18 Z" stroke="#334155" fill={on ? "#22c55e" : "#e2e8f0"} />}
    {kind === "pump" && <circle cx={12} cy={12} r={11} stroke="#334155" fill={on ? "#22c55e" : "#e2e8f0"} />}
    <text x={0} y={44} fontSize={10} fill="#0f172a">{value.toFixed(1)}</text>
  </g>;
});
let setTick;
function Display({ items, lines }) {
  const [, tick] = useState(0);
  setTick = tick;
  return <svg width="100%" height="100%" viewBox="0 0 1280 800">
    {lines.map(([a, b]) => <line key={`${a}-${b}`} x1={items[a].x + 12} y1={items[a].y + 12} x2={items[b].x} y2={items[b].y + 12} stroke="#94a3b8" strokeWidth={2} />)}
    {items.map((it) => <Item key={it.id} kind={it.kind} x={it.x} y={it.y} value={it.value} level={it.level} on={it.on} />)}
  </svg>;
}
main(async () => {
  const { items, lines, feed } = display(300);
  const r = createRoot(root());
  const render = await timed(() => flushSync(() => r.render(<Display items={items} lines={lines} />)));
  const t0 = performance.now(); feed(); flushSync(() => setTick((v) => v + 1)); const one_update_ms = +(performance.now() - t0).toFixed(1);
  const stress = await animate(STRESS_MS, () => { feed(); flushSync(() => setTick((v) => v + 1)); });
  return { render, one_update_ms, ...stress };
});
