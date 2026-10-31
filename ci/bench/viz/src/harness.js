// Shared by every bench page: data, timing and the result the runner reads (window.__result).
export const params = new URLSearchParams(location.search);
export const num = (key, fallback) => Number(params.get(key) ?? fallback);

/** Deterministic random numbers, so every library draws the same data. */
export function rng(seed = 1) {
  let s = seed >>> 0;
  return () => { s = (s + 0x6d2b79f5) >>> 0; let t = s; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

/** `pens` process-like signals of `points` values each, 1 s apart, ending now (x in epoch ms). */
export function trends(points, pens) {
  const r = rng(42);
  const t0 = Date.UTC(2026, 9, 30) - points * 1000;
  const x = new Float64Array(points);
  for (let i = 0; i < points; i++) x[i] = t0 + i * 1000;
  const ys = [];
  for (let p = 0; p < pens; p++) {
    const y = new Float64Array(points);
    // Mean-reverting around a set point that steps now and then, plus measurement noise.
    let sp = 20 + p * 8, v = sp, slow = 0;
    for (let i = 0; i < points; i++) {
      if (i % 7200 === 0 && i) sp += (r() - 0.5) * 6;
      slow = slow * 0.995 + (r() - 0.5) * 0.05;
      v += (sp - v) * 0.002 + slow;
      y[i] = v + (r() - 0.5) * 0.6;
    }
    ys.push(y);
  }
  return { x, ys };
}

export const frame = () => new Promise((ok) => requestAnimationFrame(() => ok()));
export async function frames(n = 2) { for (let i = 0; i < n; i++) await frame(); }

/** Time of `fn` until the result is on screen (two frames after it returns). */
export async function timed(fn) {
  const t0 = performance.now();
  await fn();
  await frames(2);
  return Math.round(performance.now() - t0);
}

/** Calls `step(i)` once a frame for `ms` and reports the frame times the browser achieved. */
export async function animate(ms, step) {
  const times = [];
  let last = performance.now(), i = 0;
  const end = last + ms;
  while (performance.now() < end) {
    step(i++);
    await frame();
    const now = performance.now();
    times.push(now - last);
    last = now;
  }
  times.sort((a, b) => a - b);
  const avg = times.reduce((a, b) => a + b, 0) / times.length;
  return { fps: Math.round(1000 / avg), frame_ms: +avg.toFixed(1), p95_ms: +times[Math.floor(times.length * 0.95)].toFixed(1) };
}

export const PALETTE = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#0891b2", "#db2777", "#4b5563", "#65a30d", "#ea580c"];

export function root(height = "100vh") {
  const el = document.getElementById("app");
  el.style.height = height;
  return el;
}

export function done(result) { window.__result = result; }
export function fail(error) { window.__result = { error: String(error && error.stack || error) }; }
export async function main(fn) { try { done(await fn()); } catch (e) { fail(e); } }
