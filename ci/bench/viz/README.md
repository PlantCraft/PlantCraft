# Visualization bench (plan of 2026-10-31, items C1 to C11)

Side-by-side test of the libraries the suite could draw with: the same data, the same page, the
same measurements for every candidate. Nothing here ships; the suite keeps its libraries until a
decision says otherwise.

| Item | What is drawn | Candidates (today's first) |
|---|---|---|
| C1 | Long trends: 10 pens × 50k / 100k / 200k points | Plotly (SVG), Plotly WebGL, uPlot, ECharts, Chart.js + decimation |
| C2 | 24 widget cards with a 288-point chart each | own SVG, uPlot, ECharts, Plotly |
| C3 | Scatter / correlation, 100k and 1M points | Plotly WebGL, deck.gl, regl-scatterplot |
| C4 | Heat map / spectrogram, 2000 × 500 and 4000 × 500 cells | Plotly, ECharts, own canvas |
| C5 | Process display, 300 symbols, every value changing each frame | React SVG, plain SVG, Konva, PixiJS, JointJS |
| C6 | Block editor, 200 and 400 blocks | React Flow (@xyflow/react), Rete.js, LiteGraph, Drawflow |
| C7 | Plant map / asset graph, 1000 and 2000 nodes | Cytoscape + dagre, Cytoscape + ELK, Sigma, vis-network |
| C8 | Tables, 100k and 200k rows | ui DataTable (paged), TanStack Table + Virtual, AG Grid Community, Glide Data Grid |
| C9 | Dashboard grid, 30 cards (desktop and phone) | react-grid-layout, gridstack, plain CSS grid |
| C10 | Code editor, 5000-line Python file (desktop and phone) | CodeMirror 6, Monaco |

Measured per case: time to first picture, time of the main interaction (zoom, sort, move, jump),
frames per second under load (pan, scroll, live values), JS heap after a GC, DOM nodes, and what
the case adds to a page (minified and gzipped, from the bundle esbuild writes). A screenshot of
each case goes with the numbers.

```bash
cd ci/bench/viz
npm install --legacy-peer-deps   # first time
npm run build                    # or: node build.mjs c5   (one item)
node run.mjs /tmp/viz plan.json  # results.json + prints/ in /tmp/viz
```

Set `PLAYWRIGHT_MODULE` when Playwright is installed outside this folder. WebGL cases (Plotly
WebGL, deck.gl, regl-scatterplot, PixiJS, Sigma) need a real graphics card to mean anything: in
a container without one Chromium draws WebGL in software (SwiftShader).
