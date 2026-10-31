import Plotly from "plotly.js-cartesian-dist-min";
import { main, num, root, timed } from "../harness.js";
import { spectrum } from "./common.js";
main(async () => {
  const cols = num("cols", 2000), rows = num("rows", 500);
  const flat = spectrum(cols, rows);
  const z = Array.from({ length: rows }, (_, k) => Array.from(flat.subarray(k * cols, (k + 1) * cols)));
  const el = root();
  const render = await timed(() => Plotly.newPlot(el, [{ z, type: "heatmap", colorscale: "Viridis", zsmooth: false }], { margin: { t: 10, r: 10, b: 30, l: 40 } }));
  const zoom = await timed(() => Plotly.relayout(el, { "xaxis.range": [cols * 0.4, cols * 0.5] }));
  await Plotly.relayout(el, { "xaxis.autorange": true });
  return { render, zoom };
});
