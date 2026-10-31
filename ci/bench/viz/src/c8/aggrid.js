import { createGrid, ModuleRegistry, AllCommunityModule } from "ag-grid-community";
import { main, num, root, timed, frames, animate } from "../harness.js";
import { rows as makeRows, COLS, SCROLL_MS, scrollStep } from "./common.js";
ModuleRegistry.registerModules([AllCommunityModule]);
main(async () => {
  const data = makeRows(num("n", 100000));
  const el = root();
  let api;
  const render = await timed(async () => {
    api = createGrid(el, { rowData: data, columnDefs: COLS.map((field) => ({ field, sortable: true, filter: true, width: field === "text" ? 320 : 130 })), getRowId: (p) => String(p.data.id) });
    while (!el.querySelector(".ag-row")) await frames(1);
  });
  const sort = await timed(async () => { api.applyColumnState({ state: [{ colId: "value", sort: "asc" }], defaultState: { sort: null } }); await frames(1); });
  const sortText = await timed(async () => { api.applyColumnState({ state: [{ colId: "tag", sort: "asc" }], defaultState: { sort: null } }); await frames(1); });
  const scroller = [...el.querySelectorAll("div")].find((d) => d.scrollHeight > d.clientHeight + 1000 && getComputedStyle(d).overflowY !== "hidden" && getComputedStyle(d).overflowY !== "visible");
  const scroll = await animate(SCROLL_MS, scrollStep(scroller));
  scroller.scrollTop = 0;
  return { render, sort_number: sort, sort_text: sortText, scroll_fps: scroll.fps, scroll_p95_ms: scroll.p95_ms };
});
