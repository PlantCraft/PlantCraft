import { DataTable, Pill } from "@plantcraft/ui";
import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { t } from "./i18n";
import { Link, navigate } from "./nav";
import type { Diagram, DiagramRow, DrawnItem, Me } from "./types";
import { ErrorBox, Heading, Loading, message } from "./ui";

export const CONFIDENCE_PILL: Record<string, string> = { high: "good", medium: "warning", low: "failed" };
export const CONFIDENCE_WORDS: Record<string, string> = { high: "Sure", medium: "Check", low: "Unsure" };
const FAMILY_COLOR: Record<string, string> = {
  equipment: "var(--pc-app-pidcraft, #2f7d6b)", instrument: "var(--pc-primary, #2563eb)",
  connector: "var(--pc-text-3, #888)", terminal: "var(--pc-text-3, #888)",
};

export function ConfidencePill({ value }: { value: string }) {
  return <Pill status={CONFIDENCE_PILL[value] ?? "unknown"} label={t(CONFIDENCE_WORDS[value] ?? value)} />;
}

/** Every page of the drawings that is a diagram (P&ID): what the plant map is built from. A PDF,
 * SVG, DEXPI file or scan sent in Drawings lands here when the drawing reader finds tags joined
 * by lines on a page. */
export function DiagramsPage(_props: { me: Me }) {
  const [rows, setRows] = useState<DiagramRow[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.diagrams().then(setRows).catch((err) => setError(message(err))); }, []);
  if (error) return <ErrorBox text={error} />;
  if (!rows) return <Loading />;
  return <>
    <Heading title={t("Diagrams")} />
    <p className="muted">{t("The pages of the drawings that are diagrams (P&IDs), read into equipment, instruments and the lines between them. Send P&IDs as PDF, SVG, DEXPI (XML) or images in Drawings; they appear here once read.")}</p>
    {rows.length === 0
      ? <div className="panel empty">{t("No diagram read yet.")} <Link to="/drawings">{t("Send P&IDs in Drawings")}</Link></div>
      : <DataTable rows={rows} rowKey={(row) => `${row.rev_id}:${row.page}`} label={t("Diagrams")}
        searchText={(row) => `${row.sheet} ${row.title} ${row.unit} ${row.doc_number} ${row.doc_title}`}
        searchPlaceholder={t("Search sheet, title, unit or drawing")}
        onRowClick={(row) => navigate(`/diagrams/${row.rev_id}/${row.page}`)}
        initialSort={{ key: "sheet", descending: false }}
        columns={[
          { key: "sheet", label: t("Sheet"), className: "nowrap", sort: (row) => row.sheet, render: (row) => <Link to={`/diagrams/${row.rev_id}/${row.page}`}>{row.sheet || t("Page {n}", { n: row.page })}</Link> },
          { key: "title", label: t("Title"), sort: (row) => row.title, render: (row) => row.title || "–" },
          { key: "unit", label: t("Unit"), className: "nowrap", sort: (row) => row.unit, render: (row) => row.unit || "–" },
          { key: "drawing", label: t("Drawing"), phone: "hide", sort: (row) => row.doc_number, render: (row) => <Link to={`/drawings/${row.doc_id}`}>{row.doc_number || row.doc_title}</Link> },
          { key: "items", label: t("Items"), className: "num", sort: (row) => row.items, render: (row) => row.items },
          { key: "relations", label: t("Lines"), className: "num", phone: "hide", sort: (row) => row.relations, render: (row) => row.relations },
          { key: "source", label: t("Read from"), phone: "hide", sort: (row) => row.source, render: (row) => row.source === "raster" ? t("Scan (OCR)") : row.source === "dexpi" ? t("DEXPI file") : t("Drawing") },
        ]} />}
  </>;
}

/** One diagram: the page drawn by the server with a box on each thing the reader found, and the
 * list of what it found, the doubtful first. */
/** ``pick``: a tag to show at once (a link from the plant map or from search lands on it). */
export function DiagramView({ revId, page, me, pick }: { revId: string; page: number; me?: Me; pick?: string }) {
  const [diagram, setDiagram] = useState<Diagram | null>(null);
  const [error, setError] = useState("");
  const [reading, setReading] = useState(false);
  const [readError, setReadError] = useState("");
  /** A scan read again by the language model an administrator gave "diagram-read". */
  const readWithModel = () => {
    setReading(true);
    setReadError("");
    api.readWithModel(revId, page).then(setDiagram).catch((err) => setReadError(message(err))).finally(() => setReading(false));
  };
  const [picked, setPicked] = useState<string | null>(pick ?? null);
  useEffect(() => { api.diagram(revId, page).then(setDiagram).catch((err) => setError(message(err))); }, [revId, page]);
  const items = useMemo(() => {
    const order = { low: 0, medium: 1, high: 2 };
    return [...(diagram?.result.items ?? [])].sort((a, b) => order[a.confidence] - order[b.confidence] || a.id.localeCompare(b.id));
  }, [diagram]);
  if (error) return <ErrorBox text={error} />;
  if (!diagram) return <Loading />;
  const result = diagram.result;
  const related = picked ? result.relations.filter((r) => r.from === picked || r.to === picked) : [];
  const byId = new Map(result.items.map((item) => [item.id, item]));
  const name = (id: string) => {
    const item = byId.get(id);
    if (item?.tag) return item.tag;
    if (id.startsWith("valve@")) return t("Valve without a tag");
    if (item?.family === "connector") return t("To {sheet}", { sheet: item.ref_sheet || item.label });
    return item?.label || id;
  };
  return <>
    <Heading title={`${diagram.sheet || t("Page {n}", { n: diagram.page })}${diagram.title ? ` · ${diagram.title}` : ""}`} />
    <p className="muted">
      {t("From {doc}, page {page}.", { doc: diagram.doc_number || diagram.doc_title, page: diagram.page })}{" "}
      <Link to={`/drawings/${diagram.doc_id}`}>{t("Open the drawing")}</Link>
      {result.notes.map((note) => <span key={note}> · {note}</span>)}
    </p>
    {me?.can_edit && result.source === "raster" && <p className="muted">
      {t("A scan's lines are hard to read without a model.")}{" "}
      <button type="button" className="link-button" disabled={reading} onClick={readWithModel}>{reading ? t("Reading…") : t("Read again with the language model")}</button>
    </p>}
    {readError && <ErrorBox text={readError} />}
    <div className="diagram-columns">
      <div className="panel diagram-canvas">
        <div className="diagram-frame" style={{ aspectRatio: `${result.width} / ${result.height}` }}>
          <img src={api.diagramImage(revId, page)} alt={diagram.sheet} />
          {result.items.map((item) => <ItemBox key={item.id} item={item} width={result.width} height={result.height}
            picked={picked === item.id} linked={related.some((r) => r.from === item.id || r.to === item.id)} onPick={() => setPicked(item.id === picked ? null : item.id)} />)}
        </div>
      </div>
      <div className="panel diagram-list">
        <div className="panel-header"><div><h2>{t("Found on this page")}</h2>
          <p>{t("{items} items, {lines} lines. The ones to check come first.", { items: result.items.length, lines: result.relations.length })}</p></div></div>
        {picked && <div className="diagram-picked">
          <strong>{name(picked)}</strong>
          {diagram.in_plantcraft?.includes(picked) && <p className="map-links">{t("In PlantCraft:")}{" "}
            <a href={`/assets/${encodeURIComponent(picked)}`}>{t("the asset")}</a>{" · "}
            <a href={`/assets/${encodeURIComponent(picked)}?tab=signals`}>{t("its signals")}</a>{" · "}
            <a href={`/assets/${encodeURIComponent(picked)}?tab=situation`}>{t("what the apps say")}</a></p>}
          {related.length === 0 ? <p className="muted">{t("No line joins it to anything here.")}</p>
            : <ul>{related.map((r) => <li key={`${r.from}-${r.type}-${r.to}`}>{name(r.from)} <b>{t(r.type)}</b> {name(r.to)} <ConfidencePill value={r.confidence} /></li>)}</ul>}
        </div>}
        <ul className="diagram-items">
          {items.map((item) => <li key={item.id} className={picked === item.id ? "picked" : ""}>
            <button type="button" className="link-button" onClick={() => setPicked(item.id)}>{name(item.id)}</button>
            <span className="muted"> {t(item.cls.replace("_", " "))}</span> <ConfidencePill value={item.confidence} />
            <div className="muted small">{item.why}</div>
          </li>)}
        </ul>
      </div>
    </div>
  </>;
}

function ItemBox({ item, width, height, picked, linked, onPick }: { item: DrawnItem; width: number; height: number; picked: boolean; linked: boolean; onPick: () => void }) {
  const [x0, y0, x1, y1] = item.box;
  const pad = 2;
  return <button type="button" className={`diagram-box ${item.confidence} ${picked ? "picked" : ""} ${linked ? "linked" : ""}`}
    title={`${item.tag || item.label || item.id}: ${item.why}`} aria-label={item.tag || item.label || item.id}
    style={{
      left: `${((x0 - pad) / width) * 100}%`, top: `${((y0 - pad) / height) * 100}%`,
      width: `${((x1 - x0 + 2 * pad) / width) * 100}%`, height: `${((y1 - y0 + 2 * pad) / height) * 100}%`,
      borderColor: FAMILY_COLOR[item.family] ?? "currentColor",
    }} onClick={onPick} />;
}
