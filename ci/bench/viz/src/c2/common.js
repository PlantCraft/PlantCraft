import { rng } from "../harness.js";
/** `count` widget cards in a grid, each with a title, a value and a chart box; 288 points each (24 h at 5 min). */
export function cards(count = 24) {
  const el = document.getElementById("app");
  el.style.cssText = "display:grid;grid-template-columns:repeat(6,1fr);grid-template-rows:repeat(4,1fr);gap:10px;padding:10px;box-sizing:border-box;height:100vh;width:100vw";
  const r = rng(7);
  const out = [];
  for (let c = 0; c < count; c++) {
    const card = document.createElement("div");
    card.style.cssText = "border:1px solid #e5e7eb;border-radius:8px;padding:8px;display:flex;flex-direction:column;min-height:0";
    card.innerHTML = `<div style="font-size:12px;color:#555">FIC-${1000 + c} flow</div><div style="font:600 18px system-ui">${(40 + r() * 20).toFixed(1)} m³/h</div>`;
    const box = document.createElement("div");
    box.style.cssText = "flex:1;min-height:0;position:relative";
    card.appendChild(box);
    el.appendChild(card);
    const y = []; let v = 50;
    for (let i = 0; i < 288; i++) { v += (50 - v) * 0.05 + (r() - 0.5) * 4; y.push(+v.toFixed(2)); }
    out.push({ box, y });
  }
  return out;
}
export const UPDATES = 60;
