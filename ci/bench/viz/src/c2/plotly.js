import Plotly from "plotly.js-cartesian-dist-min";
import { main, timed, frames } from "../harness.js";
import { cards, UPDATES } from "./common.js";
main(async () => {
  const list = cards();
  const layout = { margin: { t: 2, r: 0, b: 2, l: 0 }, xaxis: { visible: false }, yaxis: { visible: false }, showlegend: false };
  const render = await timed(async () => {
    for (const c of list) await Plotly.newPlot(c.box, [{ y: c.y, type: "scatter", mode: "lines", line: { width: 1.5, color: "#2563eb" } }], layout, { staticPlot: true, responsive: true });
  });
  const t0 = performance.now();
  for (let k = 0; k < UPDATES; k++) { for (const c of list) { c.y.push(c.y.shift() + 1); await Plotly.react(c.box, [{ y: c.y.slice(), type: "scatter", mode: "lines", line: { width: 1.5, color: "#2563eb" } }], layout, { staticPlot: true }); } await frames(1); }
  return { render, update_ms: +((performance.now() - t0) / UPDATES).toFixed(1) };
});
