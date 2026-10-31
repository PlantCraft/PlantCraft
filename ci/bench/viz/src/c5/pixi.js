import { Application, Container, Graphics, Text, BitmapText, BitmapFont } from "pixi.js";
import { main, root, timed, animate } from "../harness.js";
import { display, STRESS_MS } from "./common.js";
main(async () => {
  const { items, lines, feed } = display(300);
  const el = root();
  const nodes = [];
  const app = new Application();
  const render = await timed(async () => {
    await app.init({ resizeTo: el, background: "#ffffff", antialias: true, autoStart: false, preference: "webgl" });
    el.appendChild(app.canvas);
    BitmapFont.install({ name: "vals", style: { fontFamily: "system-ui", fontSize: 10, fill: "#0f172a" }, chars: [["0", "9"], ".-"] });
    const wires = new Graphics();
    for (const [a, b] of lines) wires.moveTo(items[a].x + 12, items[a].y + 12).lineTo(items[b].x, items[b].y + 12);
    wires.stroke({ width: 2, color: 0x94a3b8 });
    app.stage.addChild(wires);
    for (const it of items) {
      const g = new Container(); g.x = it.x; g.y = it.y;
      const n = { it };
      if (it.kind === "tank") { g.addChild(new Graphics().roundRect(0, 0, 24, 30, 4).fill(0xf1f5f9).stroke({ color: 0x334155, width: 1 })); n.level = new Graphics().rect(0, 0, 22, 28).fill(0x38bdf8); n.level.x = 1; g.addChild(n.level); }
      else { n.shape = it.kind === "valve" ? new Graphics().poly([0, 6, 24, 18, 24, 6, 0, 18]).fill(0xffffff).stroke({ color: 0x334155, width: 1 }) : new Graphics().circle(12, 12, 11).fill(0xffffff).stroke({ color: 0x334155, width: 1 }); g.addChild(n.shape); }
      n.text = new BitmapText({ text: "0", style: { fontFamily: "vals", fontSize: 10 } }); n.text.y = 36;
      g.addChild(n.text);
      app.stage.addChild(g);
      nodes.push(n);
    }
    paint();
  });
  function paint() {
    for (const n of nodes) {
      n.text.text = n.it.value.toFixed(1);
      if (n.level) { n.level.scale.y = n.it.level; n.level.y = 1 + 28 * (1 - n.it.level); }
      else n.shape.tint = n.it.on ? 0x22c55e : 0xe2e8f0;
    }
    app.render();
  }
  const t0 = performance.now(); feed(); paint(); const one_update_ms = +(performance.now() - t0).toFixed(1);
  const stress = await animate(STRESS_MS, () => { feed(); paint(); });
  return { render, one_update_ms, ...stress, note: "values as bitmap text (pre-drawn digits)" };
});
