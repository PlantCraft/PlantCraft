import * as echarts from "echarts/core";
import { HeatmapChart } from "echarts/charts";
import { GridComponent, VisualMapComponent, DataZoomComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { main, num, root, timed } from "../harness.js";
import { spectrum } from "./common.js";
echarts.use([HeatmapChart, GridComponent, VisualMapComponent, DataZoomComponent, CanvasRenderer]);
main(async () => {
  const cols = num("cols", 2000), rows = num("rows", 500);
  const flat = spectrum(cols, rows);
  const data = new Array(cols * rows);
  for (let k = 0; k < rows; k++) for (let c = 0; c < cols; c++) data[k * cols + c] = [c, k, flat[k * cols + c]];
  const el = root();
  const chart = echarts.init(el);
  const render = await timed(() => chart.setOption({ animation: false, grid: { left: 40, right: 60, top: 10, bottom: 50 },
    xAxis: { type: "category", data: Array.from({ length: cols }, (_, i) => i) }, yAxis: { type: "category", data: Array.from({ length: rows }, (_, i) => i) },
    visualMap: { min: 0, max: 12, calculable: false, orient: "vertical", right: 0, top: "center", inRange: { color: ["#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"] } },
    dataZoom: [{ type: "inside", xAxisIndex: 0 }, { type: "slider", xAxisIndex: 0 }],
    series: [{ type: "heatmap", data, progressive: 0 }] }));
  const zoom = await timed(() => chart.dispatchAction({ type: "dataZoom", start: 40, end: 50 }));
  chart.dispatchAction({ type: "dataZoom", start: 0, end: 100 });
  return { render, zoom };
});
