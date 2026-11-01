import { DataTable, Pill, confirmAction } from "@plantcraft/ui";
import { Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { t } from "./i18n";
import { Link, navigate } from "./nav";
import type { DiagramRow, Drawing, Me } from "./types";
import { ErrorBox, Heading, Loading, message } from "./ui";

const STATUS_PILL: Record<string, string> = { read: "good", queued: "unknown", reading: "unknown", failed: "failed" };
const STATUS_WORDS: Record<string, string> = { read: "Read", queued: "Waiting", reading: "Reading", failed: "Not read" };

function StatusPill({ status }: { status: string | null }) {
  if (!status) return <>–</>;
  return <Pill status={STATUS_PILL[status] ?? "unknown"} label={t(STATUS_WORDS[status] ?? status)} />;
}

/** The P&IDs sent to PID: each one a number, a title, a unit and its current file. A file
 * sent with the number of a drawing already here becomes its new file. */
export function DrawingsPage({ me }: { me: Me }) {
  const [rows, setRows] = useState<Drawing[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [unit, setUnit] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const load = () => api.drawings().then(setRows).catch((err) => setError(message(err)));
  useEffect(() => { void load(); }, []);
  useEffect(() => {
    if (!rows?.some((row) => row.status === "queued" || row.status === "reading")) return;
    const timer = window.setTimeout(() => void load(), 3000);
    return () => window.clearTimeout(timer);
  }, [rows]);
  const send = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    setError("");
    try {
      for (const file of Array.from(files)) await api.send(file, { unit: unit || undefined });
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
      void load();
    }
  };
  if (!rows && !error) return <Loading />;
  return <>
    <Heading title={t("Drawings")} />
    <p className="muted">{t("The plant's P&IDs as PDF, SVG, DEXPI (XML) or scans. Each file is read into tags and lines; the sheets join into the plant map. A file named like a drawing already here becomes its new revision.")}</p>
    {me.can_edit && <div className="panel drawing-send">
      <label className="field"><span>{t("Unit (optional)")}</span>
        <input value={unit} maxLength={60} onChange={(event) => setUnit(event.target.value)} placeholder="U-100" /></label>
      <input ref={input} type="file" multiple hidden accept=".pdf,.svg,.xml,.png,.jpg,.jpeg,.tif,.tiff"
        onChange={(event) => void send(event.target.files)} />
      <button type="button" className="button primary" disabled={busy} onClick={() => input.current?.click()}>
        <Upload size={16} /> {busy ? t("Sending…") : t("Send drawings")}</button>
    </div>}
    {error && <ErrorBox text={error} />}
    {rows && (rows.length === 0
      ? <div className="panel empty">{t("No drawing yet.")}</div>
      : <DataTable rows={rows} rowKey={(row) => row.drawing_id} label={t("Drawings")}
        searchText={(row) => `${row.number} ${row.title} ${row.unit} ${row.filename ?? ""}`}
        searchPlaceholder={t("Search number, title, unit or file")}
        onRowClick={(row) => navigate(`/drawings/${row.drawing_id}`)}
        initialSort={{ key: "number", descending: false }}
        columns={[
          { key: "number", label: t("Number"), className: "nowrap", sort: (row) => row.number, render: (row) => <Link to={`/drawings/${row.drawing_id}`}>{row.number}</Link> },
          { key: "title", label: t("Title"), sort: (row) => row.title, render: (row) => row.title || "–" },
          { key: "unit", label: t("Unit"), className: "nowrap", sort: (row) => row.unit, render: (row) => row.unit || "–" },
          { key: "status", label: t("Read"), sort: (row) => row.status ?? "", render: (row) => <StatusPill status={row.status} /> },
          { key: "diagrams", label: t("Sheets"), className: "num", sort: (row) => row.diagrams, render: (row) => row.diagrams },
          { key: "file", label: t("File"), phone: "hide", sort: (row) => row.filename ?? "", render: (row) => row.filename ?? "–" },
        ]} />)}
  </>;
}

/** One drawing: its file, whether it was read, and its sheets. */
export function DrawingView({ drawingId, me }: { drawingId: string; me: Me }) {
  const [drawing, setDrawing] = useState<(Drawing & { pages: DiagramRow[] }) | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.drawing(drawingId).then(setDrawing).catch((err) => setError(message(err))); }, [drawingId]);
  if (error) return <ErrorBox text={error} />;
  if (!drawing) return <Loading />;
  const remove = async () => {
    if (!(await confirmAction(t("The drawing, its revisions and what was read on it are deleted. The audit log keeps the record."), { title: t("Remove {number}?", { number: drawing.number }), confirm: t("Remove"), danger: true }))) return;
    api.remove(drawingId).then(() => navigate("/drawings")).catch((err) => setError(message(err)));
  };
  const again = () => api.readAgain(drawingId).then(() => api.drawing(drawingId)).then(setDrawing).catch((err) => setError(message(err)));
  return <>
    <Heading title={`${drawing.number}${drawing.title ? ` · ${drawing.title}` : ""}`} />
    <p className="muted">
      {drawing.filename} · <StatusPill status={drawing.status} />
      {drawing.error ? <> · {drawing.error}</> : null}
      {drawing.unit ? <> · {t("Unit {unit}", { unit: drawing.unit })}</> : null}
    </p>
    {me.can_edit && <p className="map-lists">
      <button type="button" className="link-button" onClick={() => void again()}>{t("Read again")}</button>
      <button type="button" className="link-button danger" onClick={remove}>{t("Remove")}</button>
    </p>}
    {drawing.pages.length === 0
      ? <div className="panel empty">{t("No sheet of this file was recognised as a diagram.")}</div>
      : <div className="panel"><ul className="diagram-items">{drawing.pages.map((page) =>
        <li key={`${page.rev_id}-${page.page}`}><Link to={`/diagrams/${page.rev_id}/${page.page}`}>{page.sheet || t("Page {n}", { n: page.page })}</Link>
          <span className="muted"> {t("{items} items, {lines} lines", { items: page.items, lines: page.relations })}</span></li>)}</ul></div>}
  </>;
}
