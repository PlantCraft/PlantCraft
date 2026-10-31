import Plotly from "plotly.js-gl2d-dist-min";
import { main, num, root, timed, trends, PALETTE } from "../harness.js";
main(async () => {
  const { x, ys } = trends(num("n", 200000), num("pens", 10));
  const el = root();
  const xd = Array.from(x, (v) => new Date(v));
  const render = await timed(() => Plotly.newPlot(el, ys.map((y, i) => ({ x: xd, y, type: "scattergl", mode: "lines", line: { width: 1, color: PALETTE[i] } })), { margin: { t: 10, r: 10, b: 30, l: 40 }, showlegend: false }, { responsive: true }));
  const mid = x[Math.floor(x.length / 2)], span = (x[x.length - 1] - x[0]) / 20;
  const zoom = await timed(() => Plotly.relayout(el, { "xaxis.range": [new Date(mid - span), new Date(mid + span)] }));
  const back = await timed(() => Plotly.relayout(el, { "xaxis.autorange": true }));
  return { render, zoom, unzoom: back };
});
