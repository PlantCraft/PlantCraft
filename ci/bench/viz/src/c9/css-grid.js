// Reference: plain CSS grid, no dragging (what a read-only dashboard needs).
import { main, root, timed, frames } from "../harness.js";
import { cells, cardHtml, ROW, GAP, COLS } from "./common.js";
main(async () => {
  const el = root(); el.style.overflow = "auto";
  const host = document.createElement("div");
  host.style.cssText = `display:grid;grid-template-columns:repeat(${COLS},1fr);grid-auto-rows:${ROW}px;gap:${GAP}px;padding:${GAP}px`;
  el.appendChild(host);
  const list = cells();
  const place = () => { host.innerHTML = list.map((c) => `<div style="grid-column:${c.x + 1}/span ${c.w};grid-row:${c.y + 1}/span ${c.h}">${cardHtml(c.i)}</div>`).join(""); };
  const render = await timed(place);
  const move = await timed(() => { list.find((c) => c.i === "c12").y = 0; list.find((c) => c.i === "c12").x = 0; list.forEach((c) => { if (c.i !== "c12") c.y += 3; }); place(); });
  const resize = await timed(async () => { el.style.width = "900px"; await frames(2); });
  return { render, move_card: move, relayout_900px: resize, note: "no drag or resize by hand" };
});
