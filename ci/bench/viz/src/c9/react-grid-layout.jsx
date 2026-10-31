// Today's grid (ui/src/Grid.tsx is built on react-grid-layout).
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import ReactGridLayout, { useContainerWidth } from "react-grid-layout";
import "react-grid-layout/css/styles.css";
import { main, root, timed, frames } from "../harness.js";
import { cells, cardHtml, ROW, GAP, COLS } from "./common.js";
let setOut;
function Board() {
  const [layout, setLayout] = useState(cells());
  setOut = setLayout;
  const { width, containerRef, mounted } = useContainerWidth();
  return <div ref={containerRef} style={{ width: "100%" }}>{mounted && <ReactGridLayout width={width} layout={layout} gridConfig={{ cols: COLS, rowHeight: ROW, margin: [GAP, GAP] }} onLayoutChange={setLayout}>
    {layout.map((c) => <div key={c.i}><div style={{ height: "100%" }} dangerouslySetInnerHTML={{ __html: cardHtml(c.i) }} /></div>)}
  </ReactGridLayout>}</div>;
}
main(async () => {
  const el = root(); el.style.overflow = "auto";
  const render = await timed(async () => { createRoot(el).render(<Board />); while (el.querySelectorAll(".react-grid-item").length < 30) await frames(1); });
  const move = await timed(() => flushSync(() => setOut((l) => l.map((c) => (c.i === "c12" ? { ...c, x: 0, y: 0 } : c)))));
  const resize = await timed(async () => { el.style.width = "900px"; await frames(2); });
  return { render, move_card: move, relayout_900px: resize };
});
