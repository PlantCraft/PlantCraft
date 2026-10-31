import Drawflow from "drawflow";
import "drawflow/dist/drawflow.min.css";
import { main, num, root, timed, animate } from "../harness.js";
import { blocks, PAN_MS } from "./common.js";
main(async () => {
  const { nodes, edges } = blocks(num("n", 200));
  const el = root();
  const editor = new Drawflow(el);
  const ids = [];
  const render = await timed(() => {
    editor.start();
    editor.zoom = 0.6; editor.zoom_refresh();
    for (const b of nodes) ids.push(editor.addNode(b.id, 1, 1, b.x, b.y, "blk", {}, `<div>${b.label}</div>`));
    for (const [a, b] of edges) editor.addConnection(ids[a], ids[b], "output_1", "input_1");
  });
  const pan = await animate(PAN_MS, (i) => { editor.canvas_x = -i * 8; editor.precanvas.style.transform = `translate(${editor.canvas_x}px, 0px) scale(0.6)`; });
  editor.canvas_x = 0; editor.precanvas.style.transform = "translate(0px, 0px) scale(0.6)";
  const add_node = await timed(() => editor.addNode("new", 1, 1, 100, 100, "blk", {}, "<div>New block</div>"));
  return { render, add_node, pan_fps: pan.fps, pan_p95_ms: pan.p95_ms };
});
