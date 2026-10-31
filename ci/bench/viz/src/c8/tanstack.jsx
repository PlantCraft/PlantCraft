import { useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { useReactTable, getCoreRowModel, getSortedRowModel, flexRender } from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { main, num, root, timed, frames, animate } from "../harness.js";
import { rows as makeRows, COLS, SCROLL_MS, scrollStep } from "./common.js";
const columns = COLS.map((key) => ({ accessorKey: key, header: key[0].toUpperCase() + key.slice(1), size: key === "text" ? 320 : 130 }));
let setSortingOut;
function Table({ data }) {
  const [sorting, setSorting] = useState([]);
  setSortingOut = setSorting;
  const table = useReactTable({ data, columns, state: { sorting }, onSortingChange: setSorting, getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel() });
  const scroller = useRef(null);
  const all = table.getRowModel().rows;
  const v = useVirtualizer({ count: all.length, getScrollElement: () => scroller.current, estimateSize: () => 32, overscan: 10 });
  return <div ref={scroller} id="scroller" style={{ height: "100%", overflow: "auto", font: "13px system-ui" }}>
    <div style={{ display: "flex", position: "sticky", top: 0, background: "#f8fafc", borderBottom: "1px solid #e2e8f0", zIndex: 1 }}>
      {table.getHeaderGroups()[0].headers.map((h) => <div key={h.id} onClick={h.column.getToggleSortingHandler()} style={{ width: h.getSize(), padding: "8px", fontWeight: 600, cursor: "pointer" }}>{flexRender(h.column.columnDef.header, h.getContext())}{{ asc: " ▲", desc: " ▼" }[h.column.getIsSorted()] ?? ""}</div>)}
    </div>
    <div style={{ height: v.getTotalSize(), position: "relative" }}>
      {v.getVirtualItems().map((item) => { const row = all[item.index]; return <div key={row.id} style={{ position: "absolute", top: 0, transform: `translateY(${item.start}px)`, display: "flex", height: 32, borderBottom: "1px solid #f1f5f9" }}>
        {row.getVisibleCells().map((cell) => <div key={cell.id} style={{ width: cell.column.getSize(), padding: "7px 8px", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{String(cell.getValue())}</div>)}
      </div>; })}
    </div>
  </div>;
}
main(async () => {
  const data = makeRows(num("n", 100000));
  const el = root();
  const render = await timed(async () => { createRoot(el).render(<Table data={data} />); while (!document.getElementById("scroller")) await frames(1); });
  const sort = await timed(async () => { setSortingOut([{ id: "value", desc: false }]); await frames(1); });
  const sortText = await timed(async () => { setSortingOut([{ id: "tag", desc: false }]); await frames(1); });
  const scroller = document.getElementById("scroller");
  const scroll = await animate(SCROLL_MS, scrollStep(scroller));
  scroller.scrollTop = 0;
  return { render, sort_number: sort, sort_text: sortText, scroll_fps: scroll.fps, scroll_p95_ms: scroll.p95_ms };
});
