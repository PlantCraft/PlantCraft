import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { t } from "./i18n";
import { Link } from "./nav";
import { squarify } from "./treemap";
import type { PlantMap as PlantMapData, PlantMapLoop } from "./types";

const NO_AREA = "No area";
type View = "heat" | "tree";

function fmt(value: number | null | undefined): string {
  return value === null || value === undefined ? "–" : `${Math.round(value)} %`;
}

function byArea(loops: PlantMapLoop[]): Array<[string, PlantMapLoop[]]> {
  const found = new Map<string, PlantMapLoop[]>();
  for (const loop of loops) {
    const area = loop.area || t(NO_AREA);
    found.set(area, [...(found.get(area) ?? []), loop]);
  }
  return [...found.entries()];
}

function Square({ loop, kpi, label, style }: { loop: PlantMapLoop; kpi: string; label: string; style?: React.CSSProperties }) {
  const value = loop.values[kpi];
  const title = t("{name} · {kpi} {value} · {criticality} criticality", { name: loop.name, kpi: label, value: fmt(value), criticality: t(loop.criticality) });
  const cell = <Link to={`/loops/${encodeURIComponent(loop.loop_id)}`} className={`pmap-cell pmap-${loop.bands[kpi] ?? "none"}`} title={title}>
    <span className="pmap-name">{loop.name}</span><span className="pmap-value">{fmt(value)}</span>
  </Link>;
  return style ? <div className="pmap-tree-cell" style={style}>{cell}</div> : cell;
}

/** The plant map (A6): every loop coloured by the KPI the person picks, as a heat map by area or
 * as a treemap whose rectangles are sized by the loop's criticality. Each one opens its loop. */
export function PlantMap() {
  const [data, setData] = useState<PlantMapData | null>(null);
  const [error, setError] = useState("");
  const [kpi, setKpi] = useState("health");
  const [view, setView] = useState<View>("heat");
  useEffect(() => { api.plantMap().then(setData).catch((err) => setError(err instanceof Error ? err.message : String(err))); }, []);
  const areas = useMemo(() => byArea(data?.loops ?? []), [data]);
  const tree = useMemo(() => {
    const box = { x: 0, y: 0, w: 100, h: 100 };
    return squarify(areas, ([, loops]) => loops.reduce((sum, loop) => sum + loop.weight, 0), box)
      .map((area) => ({ ...area, loops: squarify(area.item[1], (loop) => loop.weight, { x: 0, y: 0, w: 100, h: 100 }) }));
  }, [areas]);
  if (error) return <p className="muted small" role="alert">{error}</p>;
  if (!data) return <p className="muted small">{t("Reading the loops…")}</p>;
  if (!data.loops.length) return <p className="muted small">{t("No loop yet.")}</p>;
  const label = data.kpis.find((item) => item.key === kpi)?.label ?? kpi;
  return <div className="pmap" data-testid="plant-map">
    <div className="pmap-controls">
      <label className="pmap-kpi">{t("Colour by")}
        <select value={kpi} onChange={(event) => setKpi(event.target.value)}>
          {data.kpis.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
        </select>
      </label>
      <div className="segmented" role="group" aria-label={t("View")}>
        {([["heat", t("Heat map")], ["tree", t("Treemap by criticality")]] as const).map(([value, text]) => <button key={value} type="button" className={view === value ? "active" : ""} aria-pressed={view === value} onClick={() => setView(value)}>{text}</button>)}
      </div>
    </div>
    {view === "heat"
      ? <div className="pmap-heat">{areas.map(([area, loops]) => <section key={area} className="pmap-area">
          <h3>{area}</h3>
          <div className="pmap-grid">{loops.map((loop) => <Square key={loop.loop_id} loop={loop} kpi={kpi} label={label} />)}</div>
        </section>)}</div>
      : <div className="pmap-tree" role="img" aria-label={t("Treemap of the loops by area, sized by criticality, coloured by {kpi}", { kpi: label })}>
          {tree.map((area) => <div key={area.item[0]} className="pmap-tree-area" style={{ left: `${area.x}%`, top: `${area.y}%`, width: `${area.w}%`, height: `${area.h}%` }}>
            <span className="pmap-tree-label">{area.item[0]}</span>
            {area.loops.map((loop) => <Square key={loop.item.loop_id} loop={loop.item} kpi={kpi} label={label}
              style={{ position: "absolute", left: `${loop.x}%`, top: `${loop.y}%`, width: `${loop.w}%`, height: `${loop.h}%` }} />)}
          </div>)}
        </div>}
    <p className="pmap-legend muted small">
      {data.bands.map((item) => <span key={item.band}><i className={`pmap-swatch pmap-${item.band}`} />{t("from {n} %", { n: item.from })}</span>)}
      <span><i className="pmap-swatch pmap-bad" />{t("below {n} %", { n: data.bands[data.bands.length - 1]?.from ?? 50 })}</span>
      <span><i className="pmap-swatch pmap-none" />{t("not measured")}</span>
    </p>
  </div>;
}
