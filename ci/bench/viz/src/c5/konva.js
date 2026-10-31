import Konva from "konva";
import { main, root, timed, animate } from "../harness.js";
import { display, STRESS_MS } from "./common.js";
main(async () => {
  const { items, lines, feed } = display(300);
  const el = root();
  const nodes = [];
  let layer;
  const render = await timed(() => {
    const stage = new Konva.Stage({ container: el, width: el.clientWidth, height: el.clientHeight });
    layer = new Konva.Layer();
    stage.add(layer);
    for (const [a, b] of lines) layer.add(new Konva.Line({ points: [items[a].x + 12, items[a].y + 12, items[b].x, items[b].y + 12], stroke: "#94a3b8", strokeWidth: 2, listening: false }));
    for (const it of items) {
      const g = new Konva.Group({ x: it.x, y: it.y });
      const n = { it };
      if (it.kind === "tank") { g.add(new Konva.Rect({ width: 24, height: 30, cornerRadius: 4, fill: "#f1f5f9", stroke: "#334155" })); n.level = new Konva.Rect({ x: 1, width: 22, fill: "#38bdf8" }); g.add(n.level); }
      else if (it.kind === "valve") { n.shape = new Konva.Line({ points: [0, 6, 24, 18, 24, 6, 0, 18], closed: true, stroke: "#334155" }); g.add(n.shape); }
      else { n.shape = new Konva.Circle({ x: 12, y: 12, radius: 11, stroke: "#334155" }); g.add(n.shape); }
      n.text = new Konva.Text({ x: 0, y: 36, fontSize: 10, fill: "#0f172a" });
      g.add(n.text);
      layer.add(g);
      nodes.push(n);
    }
    paint();
  });
  function paint() {
    for (const n of nodes) {
      n.text.text(n.it.value.toFixed(1));
      if (n.level) { const h = 28 * n.it.level; n.level.y(1 + 28 - h); n.level.height(h); }
      else n.shape.fill(n.it.on ? "#22c55e" : "#e2e8f0");
    }
    layer.batchDraw();
  }
  const t0 = performance.now(); feed(); paint(); layer.draw(); const one_update_ms = +(performance.now() - t0).toFixed(1);
  const stress = await animate(STRESS_MS, () => { feed(); paint(); });
  return { render, one_update_ms, ...stress };
});
