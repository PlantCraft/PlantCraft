import { GridStack } from "gridstack";
import "gridstack/dist/gridstack.min.css";
import { main, root, timed, frames } from "../harness.js";
import { cells, cardHtml, ROW, GAP, COLS } from "./common.js";
main(async () => {
  const el = root(); el.style.overflow = "auto";
  const host = document.createElement("div"); host.className = "grid-stack"; el.appendChild(host);
  GridStack.renderCB = (el, w) => { el.innerHTML = w.content; };
  let grid;
  const render = await timed(() => {
    grid = GridStack.init({ column: COLS, cellHeight: ROW + GAP, margin: GAP / 2, float: false, animate: false }, host);
    grid.load(cells().map((c) => ({ id: c.i, x: c.x, y: c.y, w: c.w, h: c.h, content: cardHtml(c.i) })));
  });
  const move = await timed(() => grid.update(host.querySelector('[gs-id="c12"]'), { x: 0, y: 0 }));
  const resize = await timed(async () => { el.style.width = "900px"; await frames(2); });
  return { render, move_card: move, relayout_900px: resize, note: "no React wrapper: cards are DOM nodes we fill" };
});
