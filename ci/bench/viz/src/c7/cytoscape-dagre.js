import cytoscape from "cytoscape";
import ext from "cytoscape-dagre";
import { main, num, root, timed, animate } from "../harness.js";
import { plant, COLORS, PAN_MS } from "./common.js";
cytoscape.use(ext);
main(async () => {
  const { nodes, edges } = plant(num("n", 1000));
  const el = root();
  let cy;
  const render = await timed(() => new Promise((ok) => {
    cy = cytoscape({ container: el, elements: [...nodes.map((n) => ({ data: n })), ...edges.map((e, i) => ({ data: { id: "e" + i, source: e.s, target: e.t, kind: e.kind } }))],
      style: [{ selector: "node", style: { label: "data(label)", "font-size": 8, width: 10, height: 10, "background-color": (n) => COLORS[n.data("kind")] } },
        { selector: "edge", style: { width: 1, "line-color": "#cbd5e1", "curve-style": "haystack" } }, { selector: "edge[kind='flow']", style: { "line-color": "#f97316", "curve-style": "bezier", "target-arrow-shape": "triangle", "target-arrow-color": "#f97316", "arrow-scale": 0.5 } }],
      layout: { name: "dagre", rankDir: "LR", nodeSep: 4, rankSep: 80, animate: false, stop: () => ok() } });
  }));
  const pan = await animate(PAN_MS, (i) => cy.pan({ x: -i * 4, y: 0 }));
  cy.fit();
  return { render, pan_fps: pan.fps, pan_p95_ms: pan.p95_ms };
});
