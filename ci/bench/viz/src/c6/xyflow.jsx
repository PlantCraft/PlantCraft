import { createRoot } from "react-dom/client";
import { ReactFlow, ReactFlowProvider, useReactFlow, Background } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { main, num, root, timed, animate, frames } from "../harness.js";
import { blocks, PAN_MS } from "./common.js";
let api;
function Grab() { api = useReactFlow(); return null; }
main(async () => {
  const { nodes, edges } = blocks(num("n", 200));
  const rfNodes = nodes.map((b) => ({ id: b.id, position: { x: b.x, y: b.y }, data: { label: b.label } }));
  const rfEdges = edges.map(([a, b]) => ({ id: `e${a}-${b}`, source: `b${a}`, target: `b${b}` }));
  const el = root();
  const render = await timed(async () => {
    createRoot(el).render(<ReactFlowProvider><ReactFlow defaultNodes={rfNodes} defaultEdges={rfEdges} defaultViewport={{ x: 0, y: 0, zoom: 0.6 }} minZoom={0.1} onlyRenderVisibleElements={false}><Background /><Grab /></ReactFlow></ReactFlowProvider>);
    while (!document.querySelectorAll(".react-flow__edge").length) await frames(1);
  });
  const pan = await animate(PAN_MS, (i) => api.setViewport({ x: -i * 8, y: 0, zoom: 0.6 }));
  const add_node = await timed(() => api.addNodes({ id: "new", position: { x: 100, y: 100 }, data: { label: "New block" } }));
  api.setViewport({ x: 0, y: 0, zoom: 0.6 });
  return { render, add_node, pan_fps: pan.fps, pan_p95_ms: pan.p95_ms };
});
