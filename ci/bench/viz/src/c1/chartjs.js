import { Chart, LineController, LineElement, PointElement, LinearScale, Decimation } from "chart.js";
import { main, num, root, timed, trends, PALETTE } from "../harness.js";
Chart.register(LineController, LineElement, PointElement, LinearScale, Decimation);
main(async () => {
  const { x, ys } = trends(num("n", 200000), num("pens", 10));
  const el = root();
  const canvas = document.createElement("canvas");
  el.appendChild(canvas);
  let chart;
  const render = await timed(() => {
    chart = new Chart(canvas, { type: "line",
      data: { datasets: ys.map((y, i) => ({ data: Array.from(y, (v, k) => ({ x: x[k], y: v })), borderColor: PALETTE[i], borderWidth: 1, pointRadius: 0, indexAxis: "x" })) },
      options: { animation: false, parsing: false, normalized: true, maintainAspectRatio: false, spanGaps: true,
        plugins: { legend: { display: false }, decimation: { enabled: true, algorithm: "min-max" } },
        scales: { x: { type: "linear", ticks: { callback: (v) => new Date(v).toISOString().slice(5, 16).replace("T", " ") } }, y: { type: "linear" } } } });
  });
  const mid = x[Math.floor(x.length / 2)], span = (x[x.length - 1] - x[0]) / 20;
  const zoom = await timed(() => { chart.options.scales.x.min = mid - span; chart.options.scales.x.max = mid + span; chart.update("none"); });
  const back = await timed(() => { delete chart.options.scales.x.min; delete chart.options.scales.x.max; chart.update("none"); });
  return { render, zoom, unzoom: back };
});
