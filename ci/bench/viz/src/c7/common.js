import { rng } from "../harness.js";
/** A plant map: plant → 6 areas → units → equipment, plus process flow lines between equipment
 * (pump → exchanger → column ...). About `n` nodes in total. */
export function plant(n = 1000) {
  const r = rng(11), nodes = [{ id: "plant", label: "Riverbend plant", kind: "plant" }], edges = [];
  const equipment = [];
  const areas = 6, units = Math.max(2, Math.round(Math.sqrt(n / areas / 4)));
  const per = Math.max(2, Math.round((n - 1 - areas - areas * units) / (areas * units)));
  for (let a = 0; a < areas; a++) {
    const aid = `A${a}`; nodes.push({ id: aid, label: `Area ${a + 1}`, kind: "area" }); edges.push({ s: "plant", t: aid, kind: "part" });
    for (let u = 0; u < units; u++) {
      const uid = `${aid}U${u}`; nodes.push({ id: uid, label: `Unit ${a + 1}${String.fromCharCode(65 + u)}`, kind: "unit" }); edges.push({ s: aid, t: uid, kind: "part" });
      let prev = null;
      for (let e = 0; e < per; e++) {
        const eid = `${uid}E${e}`; const tag = ["P", "E", "V", "T", "C", "K"][e % 6] + `-${100 * (a + 1) + u * 10 + e}`;
        nodes.push({ id: eid, label: tag, kind: "equipment" }); edges.push({ s: uid, t: eid, kind: "part" });
        if (prev) edges.push({ s: prev, t: eid, kind: "flow" });
        prev = eid; equipment.push(eid);
      }
    }
  }
  for (let i = 0; i < equipment.length / 20; i++) edges.push({ s: equipment[Math.floor(r() * equipment.length)], t: equipment[Math.floor(r() * equipment.length)], kind: "flow" });
  return { nodes, edges: edges.filter((e) => e.s !== e.t) };
}
export const COLORS = { plant: "#0f172a", area: "#2563eb", unit: "#16a34a", equipment: "#d97706" };
export const PAN_MS = 2000;
