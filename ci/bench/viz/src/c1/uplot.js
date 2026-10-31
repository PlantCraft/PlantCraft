import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import { main, num, root, timed, trends, PALETTE } from "../harness.js";
main(async () => {
  const { x, ys } = trends(num("n", 200000), num("pens", 10));
  const el = root();
  const xs = new Float64Array(x.length);
  for (let i = 0; i < x.length; i++) xs[i] = x[i] / 1000;
  let plot;
  const render = await timed(() => {
    plot = new uPlot({ width: el.clientWidth, height: el.clientHeight - 40, legend: { show: false }, cursor: { drag: { x: true } },
      series: [{}, ...ys.map((_, i) => ({ stroke: PALETTE[i], width: 1 }))] }, [xs, ...ys], el);
  });
  const mid = xs[Math.floor(xs.length / 2)], span = (xs[xs.length - 1] - xs[0]) / 20;
  const zoom = await timed(() => plot.setScale("x", { min: mid - span, max: mid + span }));
  const back = await timed(() => plot.setScale("x", { min: xs[0], max: xs[xs.length - 1] }));
  return { render, zoom, unzoom: back };
});
