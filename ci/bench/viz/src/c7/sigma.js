import Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import Sigma from "sigma";
import { main, num, root, timed, animate, rng } from "../harness.js";
import { plant, COLORS, PAN_MS } from "./common.js";
main(async () => {
  const { nodes, edges } = plant(num("n", 1000));
  const el = root();
  const r = rng(2);
  let sigma;
  const render = await timed(() => {
    const g = new Graph({ multi: true });
    for (const n of nodes) g.addNode(n.id, { label: n.label, x: r(), y: r(), size: n.kind === "equipment" ? 3 : 7, color: COLORS[n.kind] });
    for (const e of edges) g.addEdge(e.s, e.t, { color: e.kind === "flow" ? "#f97316" : "#cbd5e1", size: 1, type: e.kind === "flow" ? "arrow" : "line" });
    forceAtlas2.assign(g, { iterations: 300, settings: forceAtlas2.inferSettings(g) });
    sigma = new Sigma(g, el, { renderEdgeLabels: false, labelRenderedSizeThreshold: 6 });
  });
  const cam = sigma.getCamera();
  const pan = await animate(PAN_MS, (i) => cam.setState({ x: 0.5 + i * 0.002 }));
  cam.setState({ x: 0.5, y: 0.5, ratio: 1 });
  return { render, pan_fps: pan.fps, pan_p95_ms: pan.p95_ms, note: "WebGL; layout = ForceAtlas2 300 iterations (no layered layout built in)" };
});
