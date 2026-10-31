import { main, timed, frames } from "../harness.js";
import { cards, UPDATES } from "./common.js";
// The way WidgetKinds draws today: one <svg> with a path, viewBox stretched to the box.
const W = 200, H = 60;
function path(y) {
  let lo = Infinity, hi = -Infinity;
  for (const v of y) { if (v < lo) lo = v; if (v > hi) hi = v; }
  const sx = W / (y.length - 1), sy = H / (hi - lo || 1);
  let d = "";
  for (let i = 0; i < y.length; i++) d += `${i ? "L" : "M"}${(i * sx).toFixed(1)} ${(H - (y[i] - lo) * sy).toFixed(1)}`;
  return d;
}
main(async () => {
  const list = cards();
  const render = await timed(() => {
    for (const c of list) {
      c.box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" style="width:100%;height:100%"><path fill="none" stroke="#2563eb" stroke-width="1.5" vector-effect="non-scaling-stroke"/></svg>`;
      c.path = c.box.querySelector("path");
      c.path.setAttribute("d", path(c.y));
    }
  });
  const t0 = performance.now();
  for (let k = 0; k < UPDATES; k++) { for (const c of list) { c.y.push(c.y.shift() + 1); c.path.setAttribute("d", path(c.y)); } await frames(1); }
  return { render, update_ms: +((performance.now() - t0) / UPDATES).toFixed(1) };
});
