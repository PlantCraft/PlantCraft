import { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { DataEditor, GridCellKind } from "@glideapps/glide-data-grid";
import "@glideapps/glide-data-grid/dist/index.css";
import { main, num, root, timed, frames, animate } from "../harness.js";
import { rows as makeRows, COLS, SCROLL_MS, scrollStep } from "./common.js";
let setSortOut;
function Grid({ data }) {
  const [sortKey, setSort] = useState(null);
  setSortOut = setSort;
  // Glide has no sort of its own: the rows are sorted here.
  const rows = useMemo(() => { if (!sortKey) return data; const out = data.slice(); out.sort((a, b) => (a[sortKey] < b[sortKey] ? -1 : a[sortKey] > b[sortKey] ? 1 : 0)); return out; }, [data, sortKey]);
  const columns = COLS.map((id) => ({ id, title: id[0].toUpperCase() + id.slice(1), width: id === "text" ? 320 : 130 }));
  const getCellContent = ([c, r]) => { const v = rows[r][COLS[c]]; return typeof v === "number" ? { kind: GridCellKind.Number, data: v, displayData: String(v), allowOverlay: false } : { kind: GridCellKind.Text, data: v, displayData: v, allowOverlay: false }; };
  return <DataEditor columns={columns} rows={rows.length} getCellContent={getCellContent} width="100%" height="100%" smoothScrollY />;
}
main(async () => {
  const data = makeRows(num("n", 100000));
  const el = root();
  const render = await timed(async () => { createRoot(el).render(<Grid data={data} />); while (!el.querySelector("canvas")) await frames(1); await frames(2); });
  const sort = await timed(async () => { setSortOut("value"); await frames(1); });
  const sortText = await timed(async () => { setSortOut("tag"); await frames(1); });
  const scroller = el.querySelector(".dvn-scroller");
  const scroll = scroller ? await animate(SCROLL_MS, scrollStep(scroller)) : {};
  if (scroller) scroller.scrollTop = 0;
  return { render, sort_number: sort, sort_text: sortText, scroll_fps: scroll.fps, scroll_p95_ms: scroll.p95_ms, note: "canvas; sort written by us (Glide has none)" };
});
