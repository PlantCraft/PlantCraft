import { dia, shapes } from "@joint/core";
import { main, root, timed, animate } from "../harness.js";
import { display, STRESS_MS } from "./common.js";
main(async () => {
  const { items, lines, feed } = display(300);
  const el = root();
  const graph = new dia.Graph({}, { cellNamespace: shapes });
  const cells = [];
  const render = await timed(() => {
    new dia.Paper({ el, model: graph, width: "100%", height: "100%", cellViewNamespace: shapes, interactive: false, async: false, frozen: true }).unfreeze();
    const add = [];
    for (const it of items) {
      const c = it.kind === "tank" ? new shapes.standard.Rectangle({ position: { x: it.x, y: it.y }, size: { width: 24, height: 30 } })
        : it.kind === "valve" ? new shapes.standard.Polygon({ position: { x: it.x, y: it.y }, size: { width: 24, height: 24 }, attrs: { body: { refPoints: "0,6 24,18 24,6 0,18" } } })
        : new shapes.standard.Circle({ position: { x: it.x, y: it.y }, size: { width: 24, height: 24 } });
      c.attr({ body: { stroke: "#334155", strokeWidth: 1 }, label: { fontSize: 10, refY: 44 } });
      cells.push({ c, it }); add.push(c);
    }
    for (const [a, b] of lines) add.push(new shapes.standard.Link({ source: { id: cells[a].c.id }, target: { id: cells[b].c.id }, attrs: { line: { stroke: "#94a3b8", strokeWidth: 2, targetMarker: null } } }));
    graph.resetCells(add);
    paint();
  });
  function paint() {
    for (const { c, it } of cells) c.attr({ label: { text: it.value.toFixed(1) }, body: { fill: it.kind === "tank" ? `rgba(56,189,248,${it.level})` : it.on ? "#22c55e" : "#e2e8f0" } });
  }
  const t0 = performance.now(); feed(); paint(); const one_update_ms = +(performance.now() - t0).toFixed(1);
  const stress = await animate(STRESS_MS, () => { feed(); paint(); });
  return { render, one_update_ms, ...stress, note: "tank level drawn as fill opacity (JointJS has no partial fill shape out of the box)" };
});
