import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import { main, timed, frames } from "../harness.js";
import { cards, UPDATES } from "./common.js";
main(async () => {
  const list = cards();
  const x = Array.from({ length: 288 }, (_, i) => i);
  const render = await timed(() => {
    for (const c of list) c.plot = new uPlot({ width: c.box.clientWidth, height: c.box.clientHeight, legend: { show: false }, cursor: { show: false }, axes: [{ show: false }, { show: false }], scales: { x: { time: false } }, series: [{}, { stroke: "#2563eb", width: 1.5 }] }, [x, c.y], c.box);
  });
  const t0 = performance.now();
  for (let k = 0; k < UPDATES; k++) { for (const c of list) { c.y.push(c.y.shift() + 1); c.plot.setData([x, c.y]); } await frames(1); }
  return { render, update_ms: +((performance.now() - t0) / UPDATES).toFixed(1) };
});
