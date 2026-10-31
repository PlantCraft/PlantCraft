import createScatterplot from "regl-scatterplot";
import { main, num, root, timed, frames } from "../harness.js";
import { cloud } from "./common.js";
main(async () => {
  const n = num("n", 100000);
  const { x, y } = cloud(n);
  const el = root();
  const canvas = document.createElement("canvas");
  canvas.style.cssText = "width:100%;height:100%";
  el.appendChild(canvas);
  // regl-scatterplot wants normalized device coordinates in [-1, 1].
  const points = new Array(n);
  for (let i = 0; i < n; i++) points[i] = [(x[i] - 50) / 60, (y[i] - 50) / 60];
  let plot;
  const render = await timed(async () => {
    plot = createScatterplot({ canvas, width: el.clientWidth, height: el.clientHeight, pointSize: 2, opacity: 0.4, pointColor: "#2563eb" });
    await plot.draw(points);
  });
  const zoom = await timed(async () => { plot.zoomToArea({ x: -0.2, y: -0.2, width: 0.3, height: 0.3 }, { transition: false }); await frames(1); });
  plot.zoomToOrigin({ transition: false });
  return { render, zoom, note: "no axes: lasso selection built in" };
});
