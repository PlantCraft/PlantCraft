import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, DataZoomComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { main, num, root, timed, trends, PALETTE } from "../harness.js";
echarts.use([LineChart, GridComponent, DataZoomComponent, CanvasRenderer]);
main(async () => {
  const { x, ys } = trends(num("n", 200000), num("pens", 10));
  const el = root();
  const chart = echarts.init(el, null, { renderer: "canvas" });
  const series = ys.map((y, i) => {
    const data = new Float64Array(y.length * 2);
    for (let k = 0; k < y.length; k++) { data[2 * k] = x[k]; data[2 * k + 1] = y[k]; }
    return { type: "line", data, dimensions: ["t", "v"], showSymbol: false, sampling: "lttb", large: true, progressive: 0, animation: false, lineStyle: { width: 1, color: PALETTE[i] } };
  });
  const render = await timed(() => chart.setOption({ animation: false, grid: { left: 40, right: 10, top: 10, bottom: 50 }, xAxis: { type: "time" }, yAxis: { type: "value", scale: true }, dataZoom: [{ type: "inside" }, { type: "slider" }], series }));
  const zoom = await timed(() => chart.dispatchAction({ type: "dataZoom", start: 45, end: 55 }));
  const back = await timed(() => chart.dispatchAction({ type: "dataZoom", start: 0, end: 100 }));
  return { render, zoom, unzoom: back };
});
