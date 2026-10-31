import { LiteGraph, LGraph, LGraphCanvas } from "litegraph.js";
import "litegraph.js/css/litegraph.css";
import { main, num, root, timed, animate, frames } from "../harness.js";
import { blocks, PAN_MS } from "./common.js";
function Block() { this.addInput("in", "number"); this.addInput("in2", "number"); this.addOutput("out", "number"); this.size = [160, 50]; }
Block.title = "Block";
LiteGraph.registerNodeType("bench/block", Block);
main(async () => {
  const { nodes, edges } = blocks(num("n", 200));
  const el = root();
  const canvas = document.createElement("canvas");
  canvas.width = el.clientWidth; canvas.height = el.clientHeight;
  el.appendChild(canvas);
  let graph, gc;
  const made = [];
  const render = await timed(async () => {
    graph = new LGraph();
    gc = new LGraphCanvas(canvas, graph);
    gc.ds.scale = 0.6;
    for (const b of nodes) { const n = LiteGraph.createNode("bench/block"); n.title = b.label; n.pos = [b.x, b.y]; graph.add(n); made.push(n); }
    for (const [a, b] of edges) made[a].connect(0, made[b], a + 11 === b ? 1 : 0);
    gc.draw(true, true);
  });
  const pan = await animate(PAN_MS, (i) => { gc.ds.offset[0] = -i * 8; gc.draw(true, true); });
  const add_node = await timed(() => { const n = LiteGraph.createNode("bench/block"); n.pos = [100, 100]; graph.add(n); gc.draw(true, true); });
  gc.ds.offset[0] = 0; gc.draw(true, true); await frames(2);
  return { render, add_node, pan_fps: pan.fps, pan_p95_ms: pan.p95_ms, note: "canvas; original litegraph.js is unmaintained, the maintained fork is ComfyUI's @comfyorg/litegraph" };
});
