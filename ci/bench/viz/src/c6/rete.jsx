import { NodeEditor, ClassicPreset } from "rete";
import { AreaPlugin, AreaExtensions } from "rete-area-plugin";
import { ConnectionPlugin, Presets as ConnectionPresets } from "rete-connection-plugin";
import { ReactPlugin, Presets } from "rete-react-plugin";
import { createRoot } from "react-dom/client";
import { main, num, root, timed, animate, frames } from "../harness.js";
import { blocks, PAN_MS } from "./common.js";
main(async () => {
  const { nodes, edges } = blocks(num("n", 200));
  const el = root();
  const socket = new ClassicPreset.Socket("number");
  let editor, area;
  const made = [];
  const render = await timed(async () => {
    editor = new NodeEditor();
    area = new AreaPlugin(el);
    const connection = new ConnectionPlugin();
    const reactRender = new ReactPlugin({ createRoot });
    reactRender.addPreset(Presets.classic.setup());
    connection.addPreset(ConnectionPresets.classic.setup());
    editor.use(area); area.use(connection); area.use(reactRender);
    for (const b of nodes) {
      const n = new ClassicPreset.Node(b.label);
      n.addInput("in", new ClassicPreset.Input(socket, "in", true));
      n.addOutput("out", new ClassicPreset.Output(socket, "out"));
      await editor.addNode(n);
      await area.translate(n.id, { x: b.x * 1.3, y: b.y * 1.6 });
      made.push(n);
    }
    for (const [a, b] of edges) await editor.addConnection(new ClassicPreset.Connection(made[a], "out", made[b], "in"));
    await area.area.zoom(0.45, 0, 0);
    while (!el.querySelector("[data-testid=connection]") && !el.querySelector("svg path")) await frames(1);
  });
  const pan = await animate(PAN_MS, (i) => area.area.translate(-i * 8, 0));
  const add_node = await timed(async () => { const n = new ClassicPreset.Node("New block"); await editor.addNode(n); });
  await area.area.translate(0, 0);
  return { render, add_node, pan_fps: pan.fps, pan_p95_ms: pan.p95_ms };
});
