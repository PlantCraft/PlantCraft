import { main, num, root, timed } from "../harness.js";
import { spectrum } from "./common.js";
// Own drawing: one ImageData at data resolution, scaled by the browser; colours from a 256-entry table.
const STOPS = [[68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37]];
const LUT = new Uint8Array(256 * 3);
for (let i = 0; i < 256; i++) { const f = (i / 255) * 4, a = Math.min(3, Math.floor(f)), t = f - a; for (let ch = 0; ch < 3; ch++) LUT[i * 3 + ch] = STOPS[a][ch] + (STOPS[a + 1][ch] - STOPS[a][ch]) * t; }
main(async () => {
  const cols = num("cols", 2000), rows = num("rows", 500);
  const z = spectrum(cols, rows);
  const el = root();
  const canvas = document.createElement("canvas");
  canvas.style.cssText = "position:absolute;left:40px;top:10px;width:calc(100% - 50px);height:calc(100% - 40px);image-rendering:pixelated";
  el.appendChild(canvas);
  const draw = (from, to) => {
    const w = to - from;
    canvas.width = w; canvas.height = rows;
    const ctx = canvas.getContext("2d");
    const img = ctx.createImageData(w, rows);
    for (let k = 0; k < rows; k++) for (let c = 0; c < w; c++) {
      const v = Math.max(0, Math.min(255, (z[k * cols + from + c] / 12) * 255)) | 0, p = ((rows - 1 - k) * w + c) * 4;
      img.data[p] = LUT[v * 3]; img.data[p + 1] = LUT[v * 3 + 1]; img.data[p + 2] = LUT[v * 3 + 2]; img.data[p + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
  };
  const render = await timed(() => draw(0, cols));
  const zoom = await timed(() => draw(Math.floor(cols * 0.4), Math.floor(cols * 0.5)));
  draw(0, cols);
  return { render, zoom, note: "no axes or tooltip: those are ours to write" };
});
