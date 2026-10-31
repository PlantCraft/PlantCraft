import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { main, timed, frames } from "../harness.js";
import { cards, UPDATES } from "./common.js";
echarts.use([LineChart, GridComponent, CanvasRenderer]);
main(async () => {
  const list = cards();
  const render = await timed(() => {
    for (const c of list) {
      c.chart = echarts.init(c.box);
      c.chart.setOption({ animation: false, grid: { left: 0, right: 0, top: 2, bottom: 2 }, xAxis: { type: "category", show: false }, yAxis: { type: "value", show: false, scale: true }, series: [{ type: "line", data: c.y, showSymbol: false, lineStyle: { width: 1.5, color: "#2563eb" } }] });
    }
  });
  const t0 = performance.now();
  for (let k = 0; k < UPDATES; k++) { for (const c of list) { c.y.push(c.y.shift() + 1); c.chart.setOption({ series: [{ data: c.y }] }); } await frames(1); }
  return { render, update_ms: +((performance.now() - t0) / UPDATES).toFixed(1) };
});
