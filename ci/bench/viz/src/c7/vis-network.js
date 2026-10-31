import { Network } from "vis-network/standalone";
import { main, num, root, timed, animate } from "../harness.js";
import { plant, COLORS, PAN_MS } from "./common.js";
main(async () => {
  const { nodes, edges } = plant(num("n", 1000));
  const el = root();
  let net;
  const render = await timed(() => new Promise((ok) => {
    net = new Network(el, {
      nodes: nodes.map((n) => ({ id: n.id, label: n.label, color: COLORS[n.kind], shape: "dot", size: n.kind === "equipment" ? 4 : 8, font: { size: 8 } })),
      edges: edges.map((e) => ({ from: e.s, to: e.t, color: e.kind === "flow" ? "#f97316" : "#cbd5e1", arrows: e.kind === "flow" ? "to" : undefined, smooth: false })),
    }, { layout: { hierarchical: { direction: "LR", sortMethod: "directed", levelSeparation: 150, nodeSpacing: 12 } }, physics: false, interaction: { dragNodes: false } });
    net.once("afterDrawing", () => ok());
  }));
  const pan = await animate(PAN_MS, (i) => net.moveTo({ position: { x: i * 6, y: 0 }, animation: false }));
  net.fit({ animation: false });
  return { render, pan_fps: pan.fps, pan_p95_ms: pan.p95_ms };
});
