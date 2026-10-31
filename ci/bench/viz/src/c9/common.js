/** 30 dashboard cards on a 12-column grid (91 px rows, 14 px gaps: the suite's Grid), each with a small chart. */
export const ROW = 91, GAP = 14, COLS = 12;
export function cells(n = 30) {
  const out = []; let x = 0, y = 0;
  for (let i = 0; i < n; i++) { const w = [3, 4, 6, 3, 2][i % 5], h = [2, 2, 3, 2, 1][i % 5]; if (x + w > COLS) { x = 0; y += 3; } out.push({ i: `c${i}`, x, y, w, h }); x += w; }
  return out;
}
export function cardHtml(id) {
  let d = "M0 30"; for (let k = 1; k <= 40; k++) d += ` L${k * 5} ${30 + 20 * Math.sin(k / 3 + id.length)}`;
  return `<div style="height:100%;box-sizing:border-box;border:1px solid #e2e8f0;border-radius:8px;background:#fff;padding:8px;display:flex;flex-direction:column"><b style="font-size:12px">Card ${id}</b><svg viewBox="0 0 200 60" preserveAspectRatio="none" style="flex:1;width:100%"><path d="${d}" fill="none" stroke="#2563eb" vector-effect="non-scaling-stroke"/></svg></div>`;
}
