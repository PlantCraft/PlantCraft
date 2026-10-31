import { DataTable } from "@plantcraft/ui";
import { Download } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type PointerEvent, type WheelEvent } from "react";
import { api } from "./api";
import { ConfidencePill } from "./DiagramsPage";
import { t } from "./i18n";
import { Link } from "./nav";
import type { MapItem, MapRelation, Me, PlantMap } from "./types";
import { ErrorBox, Heading, Loading, message } from "./ui";


/** The plant map: every diagram read, joined into one plant. Each sheet keeps its drawing's
 * layout as a tile, units in rows; lines that leave a sheet arrive on the next. Nothing is
 * written to PlantCraft here: the map is offered as an asset file that Assets › Import reviews. */
export function PlantMapPage(_props: { me: Me }) {
  const [plant, setPlant] = useState<PlantMap | null>(null);
  const [error, setError] = useState("");
  const [picked, setPicked] = useState<string | null>(null);
  useEffect(() => { api.plantMap().then(setPlant).catch((err) => setError(message(err))); }, []);
  if (error) return <ErrorBox text={error} />;
  if (!plant) return <Loading />;
  const s = plant.summary;
  const item = picked ? plant.items.find((i) => i.tag === picked) ?? null : null;
  return <>
    <Heading title={t("Plant map")} actions={<>
      <a className="button" href={api.assetFileUrl()} download><Download size={16} /> {t("Asset file")}</a>
      <a className="button button-primary" href="/asset-import">{t("Review in Assets › Import")}</a>
    </>} />
    <p className="muted">{t("Built from the {n} diagrams found in the documents. Download the asset file and send it on PlantCraft's Assets › Import: you review every asset there before anything changes.", { n: s.sheets })}</p>
    {s.sheets === 0 ? <div className="panel empty">{t("No diagram found in the documents yet.")} <Link to="/documents">{t("Send P&IDs in Documents")}</Link></div> : <>
      <div className="kpis map-kpis">
        <Kpi value={s.sheets} label={t("Sheets")} />
        <Kpi value={s.equipment} label={t("Equipment")} />
        <Kpi value={s.instruments} label={t("Instruments")} />
        <Kpi value={`${s.loops_complete}/${s.loops}`} label={t("Loops complete")} />
        <Kpi value={s.feeds} label={t("Process lines")} />
        <Kpi value={s.doubt_count} label={t("To check")} />
        {s.new !== null && <Kpi value={s.new} label={t("Not in PlantCraft yet")} />}
      </div>
      <div className="map-columns">
        <div className="panel map-panel"><MapCanvas plant={plant} picked={picked} onPick={setPicked} /></div>
        <div className="panel map-side">{item ? <ItemCard item={item} relations={plant.relations} onPick={setPicked} />
          : <p className="muted">{t("Click an item on the map to see its lines, its sheets and whether PlantCraft has it.")}</p>}</div>
      </div>
      <div className="panel">
        <div className="panel-header"><div><h2>{t("Plant summary")}</h2><p>{t("Units from the title blocks, areas from the sheets' titles.")}</p></div></div>
        <DataTable rows={s.units} rowKey={(u) => u.unit || "-"} label={t("Units")} columns={[
          { key: "unit", label: t("Unit"), className: "nowrap", sort: (u) => u.unit, render: (u) => u.unit || t("No unit on the sheet") },
          { key: "areas", label: t("Areas"), render: (u) => u.areas.join(", ") || "–" },
          { key: "equipment", label: t("Equipment"), render: (u) => Object.entries(u.equipment).map(([k, n]) => `${n} ${t(k.replace("_", " "))}`).join(", ") || "–" },
          { key: "instruments", label: t("Instruments"), className: "num", sort: (u) => u.instruments, render: (u) => u.instruments },
          { key: "loops", label: t("Loops"), className: "num", sort: (u) => u.loops, render: (u) => u.loops },
        ]} />
      </div>
      <div className="panel">
        <div className="panel-header"><div><h2>{t("Control loops")}</h2><p>{t("A controller with the transmitter that feeds it and the valve it moves.")}</p></div></div>
        <DataTable rows={plant.loops} rowKey={(l) => l.loop} label={t("Control loops")} initialSort={{ key: "loop", descending: false }}
          searchText={(l) => `${l.loop} ${l.transmitters.join(" ")} ${l.valves.join(" ")} ${l.equipment.join(" ")} ${l.unit} ${l.area}`}
          onRowClick={(l) => setPicked(l.loop)}
          columns={[
            { key: "loop", label: t("Loop"), className: "nowrap", sort: (l) => l.loop, render: (l) => l.loop },
            { key: "transmitters", label: t("Measured by"), render: (l) => l.transmitters.join(", ") || "–" },
            { key: "valves", label: t("Moves"), render: (l) => l.valves.join(", ") || "–" },
            { key: "equipment", label: t("On"), phone: "hide", render: (l) => l.equipment.join(", ") || "–" },
            { key: "area", label: t("Area"), phone: "hide", sort: (l) => `${l.unit} ${l.area}`, render: (l) => [l.unit, l.area].filter(Boolean).join(" · ") },
            { key: "complete", label: t("Complete"), sort: (l) => (l.complete ? 1 : 0), render: (l) => l.complete ? t("Yes") : t("No") },
          ]} />
      </div>
      {s.doubt_count > 0 && <div className="panel">
        <div className="panel-header"><div><h2>{t("To check")}</h2><p>{t("What the reader was unsure of: check it on the drawing before importing.")}</p></div></div>
        <ul className="map-doubts">{s.doubts.map((d) => <li key={d.tag}><b>{d.tag}</b> <span className="muted">{d.why}</span></li>)}</ul>
      </div>}
    </>}
  </>;
}

function Kpi({ value, label }: { value: number | string; label: string }) {
  return <div className="panel kpi-card"><span className="kpi-value">{value}</span><small>{label}</small></div>;
}

function ItemCard({ item, relations, onPick }: { item: MapItem; relations: MapRelation[]; onPick: (tag: string) => void }) {
  const mine = relations.filter((r) => r.from === item.tag || r.to === item.tag);
  return <div className="map-item">
    <h2>{item.tag}</h2>
    <p className="muted">{t(item.cls.replace("_", " "))} · {[item.unit, item.area].filter(Boolean).join(" · ") || t("no unit")}</p>
    <p><ConfidencePill value={item.confidence} /> <span className="muted">{item.why}</span></p>
    <p>{item.in_plantcraft === null ? t("PlantCraft's assets could not be read.")
      : item.in_plantcraft ? <a href={`/assets/${encodeURIComponent(item.tag)}`}>{t("In PlantCraft: open the asset")}</a>
        : t("Not in PlantCraft yet: the asset file creates it.")}</p>
    <h3>{t("Lines")}</h3>
    {mine.length === 0 ? <p className="muted">{t("None found.")}</p> : <ul>{mine.map((r) => <li key={`${r.from}-${r.type}-${r.to}`}>
      <button type="button" className="link-button" onClick={() => onPick(r.from)}>{r.from}</button> <b>{t(r.type)}</b>{" "}
      <button type="button" className="link-button" onClick={() => onPick(r.to)}>{r.to}</button> <ConfidencePill value={r.confidence} />
    </li>)}</ul>}
    <h3>{t("Drawn on")}</h3>
    {item.places.length === 0 ? <p className="muted">{t("Only named by a connector: its sheet is not in the documents.")}</p>
      : <ul>{item.places.map((p) => <li key={`${p.rev_id}-${p.page}`}><Link to={`/diagrams/${p.rev_id}/${p.page}`}>{p.sheet}</Link> <span className="muted">{p.doc_title}</span></li>)}</ul>}
  </div>;
}

const COL = 250;
const CARD_W = 150;
const CARD_H = 46;
const PILL_H = 20;

interface Card { tag: string; cls: string; x: number; y: number; loops: string[]; unit: string }

/** The plant as a flow diagram: units in rows, each piece of equipment a card placed by where
 * it sits in the process (its longest path from the feed), its control loops as pills under
 * it, the process lines as arrows; loops without equipment (headers) in a box per unit. */
export function layoutPlant(plant: PlantMap) {
  const equipment = plant.items.filter((i) => i.family === "equipment");
  const tags = new Set(equipment.map((e) => e.tag));
  const feeds = plant.relations.filter((r) => r.type === "feeds" && tags.has(r.from) && tags.has(r.to));
  const rank = new Map(equipment.map((e) => [e.tag, 0]));
  for (let pass = 0; pass < equipment.length; pass += 1) {
    let changed = false;
    for (const f of feeds) {
      const next = (rank.get(f.from) ?? 0) + 1;
      if (next > (rank.get(f.to) ?? 0) && next < equipment.length + 1) { rank.set(f.to, next); changed = true; }
    }
    if (!changed) break;
  }
  const unitOf = new Map(equipment.map((e) => [e.tag, e.unit || ""]));
  // Equipment named only by a connector takes the unit of what it is joined to.
  for (const f of feeds) {
    if (!unitOf.get(f.to)) unitOf.set(f.to, unitOf.get(f.from) ?? "");
    if (!unitOf.get(f.from)) unitOf.set(f.from, unitOf.get(f.to) ?? "");
  }
  const loopsOf = new Map<string, string[]>();
  const loose = new Map<string, string[]>();
  for (const loop of plant.loops) {
    const on = loop.equipment[0];
    if (on && tags.has(on)) loopsOf.set(on, [...(loopsOf.get(on) ?? []), loop.loop]);
    else loose.set(loop.unit || "", [...(loose.get(loop.unit || "") ?? []), loop.loop]);
  }
  const units = [...new Set([...unitOf.values(), ...loose.keys()])].sort((a, b) => (a || "~").localeCompare(b || "~"));
  const cards: Card[] = [];
  const rows: Array<{ unit: string; y: number; h: number; loose: string[] }> = [];
  let y = 0;
  for (const unit of units) {
    const mine = equipment.filter((e) => (unitOf.get(e.tag) ?? "") === unit)
      .sort((a, b) => (rank.get(a.tag)! - rank.get(b.tag)!) || a.tag.localeCompare(b.tag));
    const lanes = new Map<number, number>();
    let bottom = 0;
    for (const e of mine) {
      const r = rank.get(e.tag) ?? 0;
      const lane = lanes.get(r) ?? 0;
      const loops = loopsOf.get(e.tag) ?? [];
      const top = y + 40 + lane;
      cards.push({ tag: e.tag, cls: e.cls, x: r * COL, y: top, loops, unit });
      const used = CARD_H + 8 + Math.ceil(loops.length / 2) * (PILL_H + 4) + 24;
      lanes.set(r, lane + used);
      bottom = Math.max(bottom, lane + used);
    }
    const extra = loose.get(unit) ?? [];
    const h = Math.max(bottom, extra.length ? 80 + Math.ceil(extra.length / 2) * (PILL_H + 4) : 0) + 50;
    rows.push({ unit, y, h, loose: extra });
    y += h + 20;
  }
  const width = Math.max(...cards.map((c) => c.x + CARD_W), 600) + 220;
  return { cards, feeds, rows, width, height: Math.max(y, 300) };
}

function MapCanvas({ plant, picked, onPick }: { plant: PlantMap; picked: string | null; onPick: (tag: string) => void }) {
  const layout = useMemo(() => layoutPlant(plant), [plant]);
  const [view, setView] = useState({ x: -20, y: -10, w: layout.width + 40, h: layout.height + 20 });
  useEffect(() => setView({ x: -20, y: -10, w: layout.width + 40, h: layout.height + 20 }), [layout]);
  const drag = useRef<{ x: number; y: number } | null>(null);
  const svg = useRef<SVGSVGElement | null>(null);
  const at = new Map(layout.cards.map((c) => [c.tag, c]));
  const near = picked ? new Set(plant.relations.flatMap((r) => (r.from === picked || r.to === picked ? [r.from, r.to] : []))) : null;
  const loopEquipment = new Map(plant.loops.map((l) => [l.loop, l]));
  const onWheel = (event: WheelEvent<SVGSVGElement>) => {
    const box = svg.current?.getBoundingClientRect();
    if (!box) return;
    const k = event.deltaY > 0 ? 1.15 : 1 / 1.15;
    const mx = view.x + ((event.clientX - box.left) / box.width) * view.w;
    const my = view.y + ((event.clientY - box.top) / box.height) * view.h;
    setView({ x: mx - (mx - view.x) * k, y: my - (my - view.y) * k, w: view.w * k, h: view.h * k });
  };
  const onDown = (event: PointerEvent<SVGSVGElement>) => { drag.current = { x: event.clientX, y: event.clientY }; };
  const onMove = (event: PointerEvent<SVGSVGElement>) => {
    const box = svg.current?.getBoundingClientRect();
    if (!drag.current || !box) return;
    const dx = ((event.clientX - drag.current.x) / box.width) * view.w;
    const dy = ((event.clientY - drag.current.y) / box.height) * view.h;
    drag.current = { x: event.clientX, y: event.clientY };
    setView({ ...view, x: view.x - dx, y: view.y - dy });
  };
  const pill = (loop: string, x: number, y: number) => {
    const info = loopEquipment.get(loop);
    return <g key={loop} className={`map-pill ${info?.complete ? "" : "map-pill-open"} ${loop === picked ? "map-picked" : ""}`}
      onClick={(event) => { event.stopPropagation(); onPick(loop); }}>
      <rect x={x} y={y} width={70} height={PILL_H} rx={10} />
      <text x={x + 35} y={y + 14} textAnchor="middle">{loop}</text>
      <title>{`${loop}: ${info?.transmitters.join(", ") || "?"} → ${info?.valves.join(", ") || "?"}`}</title>
    </g>;
  };
  return <svg ref={svg} className="plant-map" viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`} role="img" aria-label={t("Plant map")}
    onWheel={onWheel} onPointerDown={onDown} onPointerMove={onMove} onPointerUp={() => { drag.current = null; }} onPointerLeave={() => { drag.current = null; }}>
    <defs><marker id="map-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" className="map-arrowhead" /></marker></defs>
    {layout.rows.map((row) => <g key={row.unit || "-"}>
      <rect x={-10} y={row.y} width={layout.width} height={row.h} rx={10} className="map-tile" />
      <text x={4} y={row.y + 24} className="map-tile-title">{row.unit || t("No unit on the sheet")}</text>
      {row.loose.length > 0 && <g>
        <text x={layout.width - 190} y={row.y + 24} className="map-loose-title">{t("Loops on headers")}</text>
        {row.loose.map((loop, k) => pill(loop, layout.width - 190 + (k % 2) * 76, row.y + 40 + Math.floor(k / 2) * (PILL_H + 4)))}
      </g>}
    </g>)}
    {layout.feeds.map((f) => {
      const a = at.get(f.from);
      const b = at.get(f.to);
      if (!a || !b) return null;
      const x1 = a.x + CARD_W;
      const y1 = a.y + CARD_H / 2;
      const x2 = b.x;
      const y2 = b.y + CARD_H / 2;
      const back = x2 <= x1;
      const d = back ? `M${x1} ${y1} C${x1 + 60} ${y1 + 80} ${x2 - 60} ${y2 + 80} ${x2} ${y2}` : `M${x1} ${y1} C${(x1 + x2) / 2} ${y1} ${(x1 + x2) / 2} ${y2} ${x2} ${y2}`;
      const hot = picked && (f.from === picked || f.to === picked);
      return <path key={`${f.from}-${f.to}`} d={d} className={`map-line map-feeds ${a.unit !== b.unit ? "map-across" : ""} ${f.confidence === "low" ? "map-unsure" : ""} ${hot ? "map-near" : ""}`} markerEnd="url(#map-arrow)" />;
    })}
    {layout.cards.map((c) => {
      const dim = near && !near.has(c.tag) && c.tag !== picked;
      return <g key={c.tag} className={`map-node map-equipment ${c.tag === picked ? "map-picked" : ""} ${dim ? "map-dim" : ""}`} onClick={(event) => { event.stopPropagation(); onPick(c.tag); }}>
        <rect x={c.x} y={c.y} width={CARD_W} height={CARD_H} rx={8} />
        <text x={c.x + 10} y={c.y + 20} className="map-card-tag">{c.tag}</text>
        <text x={c.x + 10} y={c.y + 36} className="map-card-kind">{t(c.cls.replace("_", " "))}</text>
        {c.loops.map((loop, k) => pill(loop, c.x + (k % 2) * 76, c.y + CARD_H + 8 + Math.floor(k / 2) * (PILL_H + 4)))}
      </g>;
    })}
  </svg>;
}
