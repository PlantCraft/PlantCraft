import { rng } from "../harness.js";
/** Two correlated signals (e.g. valve opening × flow) with a few operating clusters. */
export function cloud(n) {
  const r = rng(3), x = new Float32Array(n), y = new Float32Array(n);
  const gauss = () => Math.sqrt(-2 * Math.log(r() + 1e-12)) * Math.cos(2 * Math.PI * r());
  for (let i = 0; i < n; i++) {
    const mode = i % 4;
    const cx = [20, 45, 70, 85][mode];
    x[i] = cx + gauss() * 6;
    y[i] = 0.9 * x[i] + 8 * Math.sin(x[i] / 12) + gauss() * (2 + mode);
  }
  return { x, y };
}
