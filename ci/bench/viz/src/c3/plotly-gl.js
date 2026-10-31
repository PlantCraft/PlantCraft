import Plotly from "plotly.js-gl2d-dist-min";
import { main, num, root, timed } from "../harness.js";
import { cloud } from "./common.js";
main(async () => {
  const { x, y } = cloud(num("n", 100000));
  const el = root();
  const render = await timed(() => Plotly.newPlot(el, [{ x, y, type: "scattergl", mode: "markers", marker: { size: 2, color: "#2563eb", opacity: 0.4 } }], { margin: { t: 10, r: 10, b: 30, l: 40 } }));
  const zoom = await timed(() => Plotly.relayout(el, { "xaxis.range": [40, 50], "yaxis.range": [35, 55] }));
  await Plotly.relayout(el, { "xaxis.autorange": true, "yaxis.autorange": true });
  return { render, zoom };
});
