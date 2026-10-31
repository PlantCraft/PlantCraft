// Today's suite table (ui/src/DataTable.tsx): pages of 25/50/100, sort, search, filters, all in the browser.
import { createRoot } from "react-dom/client";
import { DataTable } from "../../../../../ui/src/DataTable.tsx";
import "../../../../../ui/src/tokens.css";
import "../../../../../ui/src/base.css";
import { main, num, root, timed, frames } from "../harness.js";
import { rows as makeRows, COLS } from "./common.js";
main(async () => {
  const data = makeRows(num("n", 100000));
  const el = root(); el.style.overflow = "auto"; el.style.padding = "8px";
  const columns = COLS.map((key) => ({ key, label: key[0].toUpperCase() + key.slice(1), sort: (row) => row[key], numeric: key === "value", ...(key === "state" || key === "priority" ? { filter: true } : {}) }));
  const render = await timed(async () => {
    createRoot(el).render(<DataTable rows={data} columns={columns} rowKey={(row) => String(row.id)} searchText={(row) => `${row.tag} ${row.text}`} pageSizes={[100]} />);
    while (!el.querySelector("tbody tr")) await frames(1);
  });
  const headers = [...el.querySelectorAll("th button")];
  const button = headers.find((b) => b.textContent.includes("Value"));
  const sort = await timed(async () => { button.click(); await frames(1); });
  const sortText = await timed(async () => { headers.find((b) => b.textContent.includes("Tag")).click(); await frames(1); });
  return { render, sort_number: sort, sort_text: sortText, scroll: "paged (100 rows a page)" };
});
