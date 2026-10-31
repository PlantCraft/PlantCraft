import { main, root, timed, animate } from "../harness.js";
import { display, STRESS_MS } from "./common.js";
const NS = "http://www.w3.org/2000/svg";
const mk = (tag, attrs, parent) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); parent.appendChild(e); return e; };
main(async () => {
  const { items, lines, feed } = display(300);
  const el = root();
  const nodes = [];
  const render = await timed(() => {
    const svg = mk("svg", { width: "100%", height: "100%", viewBox: "0 0 1280 800" }, el);
    for (const [a, b] of lines) mk("line", { x1: items[a].x + 12, y1: items[a].y + 12, x2: items[b].x, y2: items[b].y + 12, stroke: "#94a3b8", "stroke-width": 2 }, svg);
    for (const it of items) {
      const g = mk("g", { transform: `translate(${it.x} ${it.y})` }, svg);
      const n = { it };
      if (it.kind === "tank") { mk("rect", { width: 24, height: 30, rx: 4, fill: "#f1f5f9", stroke: "#334155" }, g); n.level = mk("rect", { x: 1, width: 22, fill: "#38bdf8" }, g); }
      else if (it.kind === "valve") n.shape = mk("path", { d: "M0 6 L24 18 L24 6 L0 18 Z", stroke: "#334155" }, g);
      else n.shape = mk("circle", { cx: 12, cy: 12, r: 11, stroke: "#334155" }, g);
      n.text = mk("text", { x: 0, y: 44, "font-size": 10, fill: "#0f172a" }, g);
      nodes.push(n);
    }
    paint();
  });
  function paint() {
    for (const n of nodes) {
      n.text.textContent = n.it.value.toFixed(1);
      if (n.level) { const h = 28 * n.it.level; n.level.setAttribute("y", 1 + 28 - h); n.level.setAttribute("height", h); }
      else n.shape.setAttribute("fill", n.it.on ? "#22c55e" : "#e2e8f0");
    }
  }
  const t0 = performance.now(); feed(); paint(); const one_update_ms = +(performance.now() - t0).toFixed(1);
  const stress = await animate(STRESS_MS, () => { feed(); paint(); });
  return { render, one_update_ms, ...stress };
});
