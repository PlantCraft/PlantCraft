import { rng } from "../harness.js";
/** A spectrogram: `cols` time slices × `rows` frequency bins (a loop oscillating at a drifting frequency). */
export function spectrum(cols, rows) {
  const r = rng(5), z = new Float32Array(cols * rows);
  for (let c = 0; c < cols; c++) {
    const peak = rows * (0.2 + 0.1 * Math.sin(c / 150));
    for (let k = 0; k < rows; k++) z[k * cols + c] = Math.exp(-((k - peak) ** 2) / 40) * 10 + Math.exp(-((k - 2 * peak) ** 2) / 80) * 4 + r() * 1.5;
  }
  return z;
}
