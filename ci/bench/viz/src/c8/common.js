import { rng } from "../harness.js";
/** `n` alarm/event rows: time, tag, description, value, unit, priority, state, area. */
export function rows(n = 100000) {
  const r = rng(13), out = new Array(n), t0 = Date.UTC(2026, 9, 1);
  const states = ["Active", "Acknowledged", "Cleared", "Shelved"], pri = ["Low", "Medium", "High", "Urgent"], units = ["m³/h", "°C", "bar", "%"];
  for (let i = 0; i < n; i++) out[i] = { id: i, time: new Date(t0 + i * 26000).toISOString().slice(0, 19).replace("T", " "), tag: `FIC-${1000 + (i % 2000)}`,
    text: `High deviation on loop ${i % 2000} in unit ${i % 37}`, value: +(r() * 200).toFixed(2), unit: units[i % 4], priority: pri[Math.floor(r() * 4)], state: states[Math.floor(r() * 4)], area: `Area ${1 + (i % 6)}` };
  return out;
}
export const COLS = ["time", "tag", "text", "value", "unit", "priority", "state", "area"];
export const SCROLL_MS = 2000;
/** Scrolls `scroller` down a bit each frame. */
export function scrollStep(scroller) { return (i) => { scroller.scrollTop = i * 400; }; }
