/** Assets › Export and Assets › Import: the tree alone (assets, records, signal references and
 * relations), in PlantCraft's JSON, Excel, CSV, ISA-95 B2MML or PI AF XML. An import is read,
 * then reviewed and edited on its own page before anything is written. */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, ArrowLeft, CheckCircle2, CircleAlert, Download, FileText, FileUp, History, LoaderCircle, Rocket, Sparkles, Undo2, Upload } from "lucide-react";
import { CopyPrompt, formatAgo, formatDate, Pill } from "@plantcraft/ui";
import { api, requestJson } from "./api";
import { modelApi, TypeIcon, type AttributeValue, type TypeCatalog } from "./assetModel";
import { assetApi, type Asset } from "./AssetsPage";
import { locale, t } from "./i18n";
import { navigate } from "./nav";
import { ADMIN_ONLY, useIsAdmin } from "./session";
import "./assets.css";
import "./sources.css";
import { Modal } from "./Modal";

export interface AssetFileFormat { id: string; label: string; detail: string }
interface FileSignal { role: string; tag: string; source_id: string }
interface FileRelation { from: string; type: string; to: string; include: boolean; status?: string; errors?: string[] }
/** Where a drafted row comes from (processcraft/platform/plantdraft.py): a rule, a document's passage or the model. */
interface DraftSource { by: "rules" | "documents" | "model"; label: string; ref?: string; section?: string; excerpt: string }
interface DraftRow { confidence: "high" | "medium" | "low"; why: string; sources: DraftSource[] }
export interface DraftSummary { tags: number; loops: number; instruments: number; equipment: number; units: number; areas: number; placed: number; by_model: number; dropped: number; unsure: number; unrecognised: number; documents?: boolean; model?: boolean }
interface DraftOptions { documents: boolean; model: boolean }
interface DataSource { source_id: string; name?: string }
interface ReviewRow {
  index: number;
  asset_id: string;
  name: string;
  type: string;
  parent_id: string;
  description: string;
  attributes: Record<string, AttributeValue>;
  signals: FileSignal[];
  include: boolean;
  status: "create" | "update" | "unchanged" | "error";
  changes: string[];
  errors: string[];
  warnings: string[];
  draft?: DraftRow;
}
interface Review {
  anchor: string;
  assets: ReviewRow[];
  relations: FileRelation[];
  counts: Record<"create" | "update" | "unchanged" | "error", number>;
  relation_counts: Record<"create" | "unchanged" | "error", number>;
  can_apply: boolean;
  file?: string;
  notes?: string[];
  applied?: boolean;
  created?: number;
  updated?: number;
  related?: number;
  draft?: DraftSummary;
}

const enc = encodeURIComponent;
export const assetFileApi = {
  formats: () => requestJson<AssetFileFormat[]>("/api/asset-file/formats"),
  read: (file: File, anchor: string) => requestJson<Review>(`/api/asset-file/read?${new URLSearchParams({ filename: file.name, ...(anchor ? { anchor } : {}) })}`, { method: "POST", body: file, headers: { "Content-Type": "application/octet-stream" } }),
  review: (document: Document) => requestJson<Review>("/api/asset-file/review", { method: "POST", body: JSON.stringify(document) }),
  apply: (document: Document) => requestJson<Review>("/api/asset-file/apply", { method: "POST", body: JSON.stringify(document) }),
  lastImport: () => requestJson<{ import: LastImport | null }>("/api/asset-file/last-import"),
  undo: () => requestJson<{ removed: number; restored: number; import: LastImport | null }>("/api/asset-file/undo", { method: "POST" }),
  draftOptions: () => requestJson<DraftOptions>("/api/asset-file/draft/options"),
  draftTags: (file: File) => requestJson<{ tags: Record<string, string>[]; notes: string[]; file: string }>(`/api/asset-file/draft/tags?${new URLSearchParams({ filename: file.name })}`, { method: "POST", body: file, headers: { "Content-Type": "application/octet-stream" } }),
  draft: (body: { source_id?: string; tags?: Record<string, string>[]; file?: string; documents: boolean; model: boolean; anchor?: string }) => requestJson<Review>("/api/asset-file/draft", { method: "POST", body: JSON.stringify(body) }),
  sources: () => requestJson<DataSource[]>("/api/data/sources"),
  startSteps: () => requestJson<{ import: LastImport | null; steps: StartStep[] }>("/api/asset-file/start"),
  takeStep: (step: StartStep) => requestJson<StartDone>(`/api/asset-file/start/${enc(step.app)}/${enc(step.id)}`, { method: "POST" }),
};

/** A first step an app takes for the assets an import wrote (``[[contributes.start]]``, D5 F4). */
interface StartStep { app: string; app_name: string; id: string; title: string; description: string; default: boolean; open: string | null }
interface StartDone { summary: string; counts: Record<string, number>; open: string | null }
type StepState = { state: "running" } | { state: "done"; done: StartDone } | { state: "failed"; error: string };

/** The newest import applied, kept so it can be taken back once (owner, 2026-10-24). */
export type LastImport = { import_id: number; at: string; actor: string; summary: { created?: number; updated?: number; relations?: number }; undone_at: string | null; undone_by: string | null; can_undo: boolean };
export const exportUrl = (kind: string, root: string) => `/api/asset-file/export.${kind}${root ? `?root=${enc(root)}` : ""}`;

type Document = { anchor: string; assets: ReviewRow[]; relations: FileRelation[] };
const KEPT = "pc.asset-import";
const STATUS_LABELS: Record<string, string> = { create: t("To create"), update: t("To update"), unchanged: t("No change"), error: t("Error"), skipped: t("Left out") };
const STATUS_TONES: Record<string, string> = { create: "good", update: "pending", unchanged: "inactive", error: "error", skipped: "inactive" };

function message(err: unknown, fallback: string) {
  return err instanceof Error ? err.message : fallback;
}

/** The review kept between the two pages (and a reload); the browser may refuse to keep it. */
function keep(review: Review | null) {
  try {
    if (review) sessionStorage.setItem(KEPT, JSON.stringify(review)); else sessionStorage.removeItem(KEPT);
  } catch { /* the review page then asks for the file again */ }
}
function kept(): Review | null {
  try {
    const value = sessionStorage.getItem(KEPT);
    return value ? JSON.parse(value) as Review : null;
  } catch { return null; }
}

/** Where assets without a parent go: the plant, a unit, an area… (assets that hold others). */
function anchorOptions(items: Asset[]) {
  const byId = new Map(items.map((item) => [item.asset_id, item]));
  const holders = new Set(items.map((item) => item.parent_id).filter(Boolean));
  const depth = (item: Asset) => { let count = 0; let parent = item.parent_id; while (parent && byId.has(parent) && count < 12) { count += 1; parent = byId.get(parent)!.parent_id; } return count; };
  const ordered: Asset[] = [];
  const children = new Map<string | null, Asset[]>();
  for (const item of items) children.set(item.parent_id, [...(children.get(item.parent_id) ?? []), item]);
  const walk = (parent: string | null) => {
    for (const item of (children.get(parent) ?? []).sort((a, b) => a.name.localeCompare(b.name, locale))) {
      if (holders.has(item.asset_id) || ["site", "unit", "area"].includes(item.kind)) { ordered.push(item); walk(item.asset_id); }
    }
  };
  walk(null);
  return ordered.map((item) => ({ id: item.asset_id, label: `${"— ".repeat(depth(item))}${item.name}` }));
}

function BackToAssets() {
  return <button className="src-back" onClick={() => navigate("/assets")}><ArrowLeft size={14} />{t("Assets")}</button>;
}

/** Assets › Export: the tree, or one branch, in the chosen format. */
export function ExportDialog({ items, rootId, onClose }: { items: Asset[]; rootId: string; onClose: () => void }) {
  const [formats, setFormats] = useState<AssetFileFormat[]>([]);
  const [kind, setKind] = useState("xlsx");
  const [root, setRoot] = useState(rootId);
  useEffect(() => { assetFileApi.formats().then(setFormats).catch(() => setFormats([])); }, []);
  const roots = useMemo(() => anchorOptions(items), [items]);
  return <Modal label={t("Export assets")} eyebrow={t("Assets")} title={t("Export assets")} description={t("The tree with each asset's record, the signals it references and its relations. Data sources are not included: they are exported in Settings.")} onClose={onClose} className="ai-export">
    <div className="form-grid">
      <label className="field-span">{t("What to export")}<select value={root} onChange={(event) => setRoot(event.target.value)}>{roots.map((item) => <option key={item.id} value={item.id}>{item.id === rootId ? t("The whole plant") : item.label}</option>)}</select></label>
      <fieldset className="field-span ai-formats" role="radiogroup" aria-label={t("Format")}>
        <legend>{t("Format")}</legend>
        {formats.map((item) => <label key={item.id} className={kind === item.id ? "active" : ""}>
          <input type="radio" name="asset-format" checked={kind === item.id} onChange={() => setKind(item.id)} />
          <span><strong>{item.label}</strong><small>{item.detail}</small></span>
        </label>)}
      </fieldset>
    </div>
    <footer><button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button><a className="button button-primary" href={exportUrl(kind, root === rootId ? "" : root)} download onClick={() => window.setTimeout(onClose, 300)}><Download size={15} /> {t("Download")}</a></footer>
  </Modal>;
}

/** Assets › Import, step 1: choose the file and where it goes. */
export function AssetImportPage() {
  const isAdmin = useIsAdmin();
  const [items, setItems] = useState<Asset[]>([]);
  const [rootId, setRootId] = useState("");
  const [anchor, setAnchor] = useState("");
  const [formats, setFormats] = useState<AssetFileFormat[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    assetApi.tree().then((tree) => { setItems(tree.items); setRootId(tree.root_id); setAnchor((current) => current || tree.root_id); }).catch((err) => setError(message(err, t("Couldn't load."))));
    assetFileApi.formats().then(setFormats).catch(() => setFormats([]));
  }, []);
  const anchors = useMemo(() => anchorOptions(items), [items]);
  async function read(file: File | null) {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      keep(await assetFileApi.read(file, anchor === rootId ? "" : anchor));
      navigate("/asset-import/review");
    } catch (err) {
      setError(message(err, t("Could not read the file.")));
    } finally {
      setBusy(false);
    }
  }
  return <>
    <div className="page-heading"><div><BackToAssets /><h1>{t("Import assets")}</h1><p>{t("Add or update assets from a file: the tree, each asset's record, the signals it references and its relations. Nothing is written until you review it on the next page.")}</p></div></div>
    <div className="map-grid">
      <section className="panel map-card">
        <h2>{t("1. Choose the file")}</h2>
        <label className="as-filter ai-anchor"><span>{t("Place under")}</span><select value={anchor} onChange={(event) => setAnchor(event.target.value)} aria-label={t("Place under")}>{anchors.map((item) => <option key={item.id} value={item.id}>{item.id === rootId ? t("The plant ({name})", { name: items.find((asset) => asset.asset_id === rootId)?.name ?? rootId }) : item.label}</option>)}</select></label>
        <p className="src-hint">{t("Assets whose parent is not in the file or in the tree go here.")}</p>
        <label className={`map-drop${isAdmin ? "" : " ai-disabled"}`} title={isAdmin ? undefined : ADMIN_ONLY}>
          {busy ? <LoaderCircle className="spin" size={22} /> : <FileUp size={22} />}
          <strong>{busy ? t("Reading the file…") : t("Choose the assets file")}</strong>
          <small>{t(".json, .xlsx, .csv or .xml (ISA-95 B2MML or PI AF)")}</small>
          <input type="file" accept=".json,.xlsx,.csv,.xml" aria-label={t("Assets file")} disabled={!isAdmin || busy} onChange={(event) => { void read(event.target.files?.[0] ?? null); event.target.value = ""; }} />
        </label>
        {error && <div className="module-state module-error"><AlertTriangle /><span>{error}</span></div>}
      </section>
      <DraftPanel anchor={anchor === rootId ? "" : anchor} />
      <section className="panel map-card">
        <h2>{t("Formats read")}</h2>
        <ul className="ai-format-list">{formats.map((item) => <li key={item.id}><strong>{item.label}</strong><span>{item.detail}</span></li>)}</ul>
        <p className="src-hint">{t("To start a file by hand, export the current tree in Excel and edit it.")}</p>
      </section>
      <section className="panel map-card">
        <h2>{t("With an AI assistant")}</h2>
        <p className="src-hint">{t("The tree is in another system, a spreadsheet or the plant's documents? Copy a prompt for your AI assistant: it explains the JSON file this page reads and lists your asset types. Attach the documents or paste the export, save the answer as a .json file and choose it above.")}</p>
        <CopyPrompt build={api.assetTreePrompt} questions={[{ id: "build", label: t("Build the tree from documents") }, { id: "convert", label: t("Convert another system's export") }, { id: "review", label: t("Review an asset file") }]} />
      </section>
      <LastImportPanel />
    </div>
  </>;
}

/** Assets › Import › Draft a new plant (owner decision D5, 2026-10-27): the first tree drafted from
 * the plant's tags, placed by its documents and, for what stays unsure, a language model. The
 * draft opens on the review page like a file: nothing is written until it is applied. */
function DraftPanel({ anchor }: { anchor: string }) {
  const isAdmin = useIsAdmin();
  const [options, setOptions] = useState<DraftOptions | null>(null);
  const [sources, setSources] = useState<DataSource[]>([]);
  const [source, setSource] = useState("");
  const [documents, setDocuments] = useState(true);
  const [model, setModel] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!isAdmin) return;
    assetFileApi.draftOptions().then(setOptions).catch(() => setOptions({ documents: false, model: false }));
    assetFileApi.sources().then((items) => { setSources(items); setSource((current) => current || items[items.length - 1]?.source_id || ""); }).catch(() => setSources([]));
  }, [isAdmin]);
  async function run(body: { source_id?: string; tags?: Record<string, string>[]; file?: string }) {
    setBusy(true);
    setError("");
    try {
      keep(await assetFileApi.draft({ ...body, documents: documents && !!options?.documents, model: model && !!options?.model, ...(anchor ? { anchor } : {}) }));
      navigate("/asset-import/review");
    } catch (err) {
      setError(message(err, t("Could not draft the plant.")));
    } finally {
      setBusy(false);
    }
  }
  async function fromFile(file: File | null) {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const read = await assetFileApi.draftTags(file);
      await run({ tags: read.tags, file: read.file });
    } catch (err) {
      setError(message(err, t("Could not read the tag list.")));
      setBusy(false);
    }
  }
  const disabled = !isAdmin || busy;
  return <section className="panel map-card ai-draft" aria-labelledby="ai-draft-title">
    <h2 id="ai-draft-title"><Sparkles size={16} /> {t("Draft a new plant")}</h2>
    <p className="src-hint">{t("No asset file yet? PlantCraft drafts the tree from the plant's tags: loops, their signals, transmitters and valves by ISA-5.1 names, then units, areas and equipment from the plant's documents, each row with its source. You review it on the next page.")}</p>
    <div className="ai-draft-from">
      <label className="as-filter"><span>{t("Tags of a source")}</span><select value={source} disabled={disabled || !sources.length} onChange={(event) => setSource(event.target.value)} aria-label={t("Source")}>
        {!sources.length && <option value="">{t("No source yet")}</option>}
        {sources.map((item) => <option key={item.source_id} value={item.source_id}>{item.name || item.source_id}</option>)}
      </select></label>
      <button type="button" className="button button-secondary" disabled={disabled || !source} title={isAdmin ? undefined : ADMIN_ONLY} onClick={() => void run({ source_id: source })}>{busy ? <LoaderCircle className="spin" size={15} /> : <Sparkles size={15} />}{t("Draft from the source")}</button>
      <label className={`button button-secondary ai-draft-file${disabled ? " ai-disabled" : ""}`}>
        <FileUp size={15} />{t("Draft from a tag list")}
        <input type="file" accept=".csv,.xlsx,.txt" aria-label={t("Tag list")} disabled={disabled} onChange={(event) => { void fromFile(event.target.files?.[0] ?? null); event.target.value = ""; }} />
      </label>
    </div>
    <p className="src-hint">{t("A tag list is a .csv or .xlsx with a tag column and, if you have them, description and engineering units.")}</p>
    <label className="ai-check"><input type="checkbox" checked={documents && !!options?.documents} disabled={disabled || !options?.documents} onChange={(event) => setDocuments(event.target.checked)} />{options?.documents ? t("Place them with the plant's documents (Documents)") : t("Place them with the plant's documents: install Documents and send the manuals, narratives, P&ID index and datasheets")}</label>
    <label className="ai-check"><input type="checkbox" checked={model && !!options?.model} disabled={disabled || !options?.model} onChange={(event) => setModel(event.target.checked)} />{options?.model ? t("Let the language model place what stays unsure (it reads tag names and document passages only)") : t('Language model: choose one for "Plant draft" in Settings › Language models')}</label>
    {error && <div className="module-state module-error"><AlertTriangle /><span>{error}</span></div>}
  </section>;
}

const CONFIDENCE_LABELS: Record<string, string> = { high: t("Sure"), medium: t("Check"), low: t("Unsure") };
const CONFIDENCE_TONES: Record<string, string> = { high: "good", medium: "pending", low: "attention" };

/** The rows under a row, itself included: leaving out a unit leaves out what the draft put in it. */
function subtree(rows: ReviewRow[], id: string): Set<string> {
  const found = new Set([id]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const row of rows) if (!found.has(row.asset_id) && found.has(row.parent_id)) { found.add(row.asset_id); grew = true; }
  }
  return found;
}

function sourceLink(source: DraftSource) {
  const id = source.ref?.startsWith("doc:") ? source.ref.slice(4) : "";
  return id ? `/doc/documents/${enc(id)}` : "";
}

/** The last import and one way back from it: what it created goes, what it overwrote returns. */
export function LastImportPanel() {
  const isAdmin = useIsAdmin();
  const [last, setLast] = useState<LastImport | null | undefined>(undefined);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => { if (isAdmin) assetFileApi.lastImport().then((found) => setLast(found.import)).catch(() => setLast(null)); }, [isAdmin]);
  if (!isAdmin || last === undefined) return null;
  async function undo() {
    setBusy(true);
    setError("");
    try {
      const done = await assetFileApi.undo();
      setLast(done.import);
      setNotice(t("Import undone. Assets removed: {removed}. Assets restored: {restored}.", { removed: done.removed, restored: done.restored }));
    } catch (err) {
      setError(message(err, t("Couldn't undo the import.")));
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  }
  const counts = last?.summary ?? {};
  return <section className="panel map-card ai-last" aria-labelledby="ai-last-title">
    <h2 id="ai-last-title"><History size={16} /> {t("Last import")}</h2>
    {!last && <p className="src-hint">{t("No import applied yet. Each import can be undone once, until the next one.")}</p>}
    {last && <>
      <p><strong>{t("{created} created, {updated} updated, {related} relations added.", { created: counts.created ?? 0, updated: counts.updated ?? 0, related: counts.relations ?? 0 })}</strong></p>
      <p className="src-hint" title={formatDate(last.at)}>{t("By {person}, {ago}.", { person: last.actor, ago: formatAgo(last.at) })}</p>
      {last.undone_at && <p className="src-hint">{t("Undone by {person}, {ago}.", { person: last.undone_by ?? "", ago: formatAgo(last.undone_at) })}</p>}
      {last.can_undo && !confirming && <div className="heading-actions"><button type="button" className="button button-secondary" disabled={busy} onClick={() => setConfirming(true)}><Undo2 /> {t("Undo last import")}</button></div>}
      {confirming && <div className="ai-confirm" role="alert">
        <p>{t("The assets this import created are deleted, with anything added to them since. Records it changed go back to how they were before it. Relations and signals it added are removed.")}</p>
        <div className="heading-actions"><button type="button" className="button button-danger" disabled={busy} onClick={() => void undo()}>{busy ? <LoaderCircle className="spin" /> : <Undo2 />} {t("Undo the import")}</button><button type="button" className="button button-secondary" disabled={busy} onClick={() => setConfirming(false)}>{t("Cancel")}</button></div>
      </div>}
    </>}
    {notice && <p className="ai-done"><CheckCircle2 size={14} /> {notice}</p>}
    {error && <div className="module-state module-error"><AlertTriangle /><span>{error}</span></div>}
  </section>;
}

/** After an import: the first steps the installed apps take for the assets it wrote (collect
 * their signals, monitor their loops, draft their alarms, draw their overviews). Each is sent to
 * its app as this administrator; a step may be taken again after a later import. */
export function StartPanel() {
  const [steps, setSteps] = useState<StartStep[] | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [states, setStates] = useState<Record<string, StepState>>({});
  const [busy, setBusy] = useState(false);
  const key = (step: StartStep) => `${step.app}:${step.id}`;
  useEffect(() => {
    assetFileApi.startSteps().then((found) => {
      setSteps(found.steps);
      setChosen(new Set(found.steps.filter((step) => step.default).map(key)));
    }).catch(() => setSteps([]));
  }, []);
  if (!steps?.length) return null;
  async function take() {
    setBusy(true);
    for (const step of steps ?? []) {
      if (!chosen.has(key(step))) continue;
      setStates((now) => ({ ...now, [key(step)]: { state: "running" } }));
      try {
        const done = await assetFileApi.takeStep(step);
        setStates((now) => ({ ...now, [key(step)]: { state: "done", done } }));
      } catch (err) {
        setStates((now) => ({ ...now, [key(step)]: { state: "failed", error: message(err, t("The app did not take the step.")) } }));
      }
    }
    setBusy(false);
  }
  const toggle = (step: StartStep) => setChosen((now) => {
    const next = new Set(now);
    if (next.has(key(step))) next.delete(key(step)); else next.add(key(step));
    return next;
  });
  return <section className="panel start-steps">
    <h2><Rocket size={16} /> {t("First steps in the apps")}</h2>
    <p className="src-hint">{t("The apps can start on the assets you imported. Each step is taken as you, with your access in that app; nothing is switched on without review.")}</p>
    <ul>
      {steps.map((step) => {
        const now = states[key(step)];
        const open = now?.state === "done" ? now.done.open ?? step.open : step.open;
        return <li key={key(step)} className="start-step">
          <label><input type="checkbox" checked={chosen.has(key(step))} disabled={busy || now?.state === "done"} onChange={() => toggle(step)} /> <strong>{step.app_name}: {step.title}</strong></label>
          {step.description && <p className="src-hint">{step.description}</p>}
          {now?.state === "running" && <p className="start-state"><LoaderCircle className="spin" size={14} /> {t("Working…")}</p>}
          {now?.state === "done" && <p className="start-state"><CheckCircle2 size={14} /> {now.done.summary} {open && <a href={open}>{t("Open")}</a>}</p>}
          {now?.state === "failed" && <p className="start-state start-failed"><CircleAlert size={14} /> {now.error}</p>}
        </li>;
      })}
    </ul>
    <div className="heading-actions"><button type="button" className="button button-primary" disabled={busy || ![...chosen].some((item) => states[item]?.state !== "done")} onClick={() => void take()}>{busy ? <LoaderCircle className="spin" /> : <Rocket />} {t("Take the chosen steps")}</button></div>
  </section>;
}

/** Assets › Import, step 2: the file as a tree, to edit and leave rows out before applying. */
export function AssetImportReview() {
  const isAdmin = useIsAdmin();
  const [review, setReview] = useState<Review | null>(() => kept());
  const [items, setItems] = useState<Asset[]>([]);
  const [rootId, setRootId] = useState("");
  const [catalog, setCatalog] = useState<TypeCatalog | null>(null);
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState<"review" | "apply" | null>(null);
  const [error, setError] = useState("");
  const [done, setDone] = useState<Review | null>(null);
  const pending = useRef<number | undefined>(undefined);
  useEffect(() => {
    assetApi.tree().then((tree) => { setItems(tree.items); setRootId(tree.root_id); }).catch(() => undefined);
    modelApi.types().then(setCatalog).catch(() => undefined);
    return () => window.clearTimeout(pending.current);
  }, []);
  const types = useMemo(() => (catalog?.types ?? []).filter((item) => item.id !== "site").sort((a, b) => a.name.localeCompare(b.name, locale)), [catalog]);
  const icons = useMemo(() => Object.fromEntries((catalog?.types ?? []).map((item) => [item.id, item.icon])), [catalog]);
  const names = useMemo(() => new Map(items.map((item) => [item.asset_id, item.name])), [items]);
  const anchors = useMemo(() => anchorOptions(items), [items]);
  if (done) return <>
    <div className="page-heading"><div><BackToAssets /><h1>{t("Assets imported")}</h1></div></div>
    <section className="panel map-result"><CheckCircle2 /><div>
      <strong>{t("{created} created, {updated} updated, {related} relations added.", { created: done.created ?? 0, updated: done.updated ?? 0, related: done.related ?? 0 })}</strong>
      <p>{t("Each change is in the asset's history.")}</p>
      <p className="src-hint">{t("Changed your mind? The import can be undone from the Import page until the next one is applied.")}</p>
      <div className="map-downloads heading-actions"><button className="button button-primary" onClick={() => navigate("/assets")}>{t("Open the assets")}</button><button className="button button-secondary" onClick={() => navigate("/asset-import")}>{t("Import another file")}</button></div>
    </div></section>
    <StartPanel />
  </>;
  if (!review) return <>
    <div className="page-heading"><div><BackToAssets /><h1>{t("Review the import")}</h1></div></div>
    <section className="panel"><p className="muted">{t("No file read yet.")}</p><button className="button button-primary" onClick={() => navigate("/asset-import")}><FileUp size={15} /> {t("Choose a file")}</button></section>
  </>;
  const current = review;
  const inFile = new Set(current.assets.map((row) => row.asset_id));
  const children = new Map<string, ReviewRow[]>();
  const tops: ReviewRow[] = [];
  for (const row of current.assets) {
    if (row.parent_id && inFile.has(row.parent_id) && row.parent_id !== row.asset_id) children.set(row.parent_id, [...(children.get(row.parent_id) ?? []), row]);
    else tops.push(row);
  }
  const unsure = (row: ReviewRow) => !!row.draft && row.draft.confidence !== "high";
  const shown = (row: ReviewRow): boolean => !filter || (filter === "out" ? !row.include : filter === "unsure" ? row.include && unsure(row) : row.include && row.status === filter) || (children.get(row.asset_id) ?? []).some(shown);
  function document(next: Review): Document {
    return { anchor: next.anchor, assets: next.assets, relations: next.relations };
  }
  function edit(next: Review) {
    setReview(next);
    keep(next);
    window.clearTimeout(pending.current);
    pending.current = window.setTimeout(() => {
      setBusy("review");
      assetFileApi.review(document(next))
        .then((checked) => { const merged = { ...checked, file: next.file, notes: next.notes, draft: next.draft }; setReview(merged); keep(merged); setError(""); })
        .catch((err) => setError(message(err, t("Could not review the file."))))
        .finally(() => setBusy(null));
    }, 450);
  }
  const change = (index: number, patch: Partial<ReviewRow>) => edit({ ...current, assets: current.assets.map((row) => (row.index === index ? { ...row, ...patch } : row)) });
  // A draft's unit or area goes in or out with everything the draft placed under it.
  const include = (row: ReviewRow, value: boolean) => {
    if (!current.draft) return change(row.index, { include: value });
    const ids = subtree(current.assets, row.asset_id);
    edit({ ...current, assets: current.assets.map((item) => (ids.has(item.asset_id) ? { ...item, include: value } : item)) });
  };
  async function apply() {
    setBusy("apply");
    try {
      const result = await assetFileApi.apply(document(current));
      if (result.applied) { keep(null); setDone(result); }
      else { setReview({ ...result, file: current.file, notes: current.notes, draft: current.draft }); setError(t("The file has errors; nothing was changed.")); }
    } catch (err) {
      setError(message(err, t("Could not import the assets.")));
    } finally {
      setBusy(null);
    }
  }
  const counts = current.counts;
  const out = current.assets.filter((row) => !row.include).length;
  const relations = current.relation_counts;
  const parentLabel = (id: string) => names.get(id) ?? id;
  const renderRow = (row: ReviewRow, depth: number): ReactNode => {
    if (!shown(row)) return null;
    const nested = children.get(row.asset_id) ?? [];
    return <li key={row.index}>
      <div className={`ai-row${row.include ? "" : " ai-out"}`} style={{ paddingLeft: depth * 22 }}>
        <input type="checkbox" checked={row.include} disabled={!isAdmin} aria-label={t("Include {asset}", { asset: row.asset_id })} onChange={(event) => include(row, event.target.checked)} />
        <span className="ai-icon"><TypeIcon icon={icons[row.type]} kind={row.type} /></span>
        <code className="ai-id">{row.asset_id || "—"}</code>
        <input className="ai-name" value={row.name} maxLength={200} disabled={!isAdmin || !row.include} aria-label={t("Name of {asset}", { asset: row.asset_id })} onChange={(event) => change(row.index, { name: event.target.value })} />
        <select className="ai-type" value={types.some((item) => item.id === row.type) ? row.type : ""} disabled={!isAdmin || !row.include} aria-label={t("Type of {asset}", { asset: row.asset_id })} onChange={(event) => change(row.index, { type: event.target.value })}>
          {!types.some((item) => item.id === row.type) && <option value="">{row.type || t("Choose a type")}</option>}
          {types.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
        {depth === 0 ? <select className="ai-parent" value={row.parent_id} disabled={!isAdmin || !row.include} aria-label={t("Parent of {asset}", { asset: row.asset_id })} onChange={(event) => change(row.index, { parent_id: event.target.value })}>
          {!anchors.some((item) => item.id === row.parent_id) && <option value={row.parent_id}>{row.parent_id === rootId ? t("Under the plant") : t("Under {parent}", { parent: parentLabel(row.parent_id) })}</option>}
          {anchors.map((item) => <option key={item.id} value={item.id}>{item.id === rootId ? t("Under the plant") : t("Under {parent}", { parent: item.label.replace(/^(— )+/, "") })}</option>)}
        </select> : <span className="ai-parent ai-inherit">{t("Under {parent}", { parent: current.assets.find((item) => item.asset_id === row.parent_id)?.name ?? row.parent_id })}</span>}
        {row.draft && row.include && <span className="ai-confidence" title={row.draft.why}><Pill status={CONFIDENCE_TONES[row.draft.confidence]} label={CONFIDENCE_LABELS[row.draft.confidence]} /></span>}
        <span className="ai-status">{row.include ? <Pill status={STATUS_TONES[row.status]} label={STATUS_LABELS[row.status]} /> : <Pill status="inactive" label={t("Left out")} />}</span>
      </div>
      {row.include && (row.errors.length > 0 || row.warnings.length > 0 || (row.status === "update" && row.changes.length > 0) || row.signals.length > 0 || !!row.draft) && <div className="ai-notes" style={{ paddingLeft: depth * 22 + 52 }}>
        {row.errors.map((text, index) => <p key={`e${index}`} className="ai-error"><CircleAlert size={13} /> {text}</p>)}
        {row.warnings.map((text, index) => <p key={`w${index}`} className="ai-warning"><AlertTriangle size={13} /> {text}</p>)}
        {row.status === "update" && row.changes.length > 0 && <p className="ai-changes">{t("Changes: {fields}", { fields: row.changes.map(changeLabel).join(", ") })}</p>}
        {row.signals.length > 0 && <p className="ai-signals">{t("Signals: {signals}", { signals: row.signals.map((item) => (item.role ? `${item.role} = ${item.tag}` : item.tag)).join(", ") })}</p>}
        {row.draft && <p className="ai-why">{row.draft.why}</p>}
        {row.draft && row.draft.sources.filter((source) => source.by !== "rules").map((source, index) => {
          const href = sourceLink(source);
          return <p key={`s${index}`} className="ai-source"><FileText size={13} />{href ? <a href={href}>{source.label || t("Document")}</a> : <strong>{source.by === "model" ? t("Language model") : source.label}</strong>}<q>{source.excerpt}</q></p>;
        })}
      </div>}
      {nested.length > 0 && <ul>{nested.map((child) => renderRow(child, depth + 1))}</ul>}
    </li>;
  };
  const toCheck = current.assets.filter((row) => row.include && unsure(row)).length;
  const filters: [string, string, number][] = [["", t("All"), current.assets.length], ...(current.draft ? [["unsure", t("To check"), toCheck] as [string, string, number]] : []), ["create", t("To create"), counts.create], ["update", t("To update"), counts.update], ["error", t("Errors"), counts.error], ["unchanged", t("No change"), counts.unchanged], ["out", t("Left out"), out]];
  const drafted = current.draft;
  const writes = counts.create + counts.update + relations.create;
  return <>
    <div className="page-heading">
      <div><button className="src-back" onClick={() => navigate("/asset-import")}><ArrowLeft size={14} />{t("Import assets")}</button><h1>{t("Review the import")}</h1><p>{t("{file}: check each asset, correct the name, type or place, and leave out what should not come in. Nothing is written until you apply.", { file: current.file ?? t("The file") })}</p></div>
      <div className="heading-actions">
        <button className="button button-secondary" onClick={() => { keep(null); navigate("/asset-import"); }}>{t("Cancel")}</button>
        <button className="button button-primary" disabled={!isAdmin || !current.can_apply || busy !== null} title={isAdmin ? undefined : ADMIN_ONLY} onClick={() => void apply()}>{busy === "apply" ? <LoaderCircle className="spin" size={15} /> : <Upload size={15} />}{t("Apply")}</button>
      </div>
    </div>
    <section className="panel ai-summary" aria-live="polite">
      <p>
        {counts.error ? <strong className="ai-error-text">{counts.error === 1 ? t("1 asset has an error: correct it or leave it out.") : t("{count} assets have errors: correct them or leave them out.", { count: counts.error })} </strong> : null}
        {writes ? t("{create} new, {update} with changes, {unchanged} already as in the file, {relations} new relations.", { create: counts.create, update: counts.update, unchanged: counts.unchanged, relations: relations.create }) : t("Nothing changes: the tree already matches the file.")}
        {busy === "review" && <LoaderCircle className="spin" size={14} />}
      </p>
      <label className="as-filter"><span>{t("Assets without a parent go")}</span><select value={current.anchor} disabled={!isAdmin} onChange={(event) => edit({ ...current, anchor: event.target.value, assets: current.assets.map((row) => (row.parent_id === current.anchor ? { ...row, parent_id: event.target.value } : row)) })}>{anchors.map((item) => <option key={item.id} value={item.id}>{item.id === rootId ? t("Under the plant") : item.label}</option>)}</select></label>
    </section>
    {error && <div className="module-state module-error"><AlertTriangle /><span>{error}</span></div>}
    {drafted && <section className="panel ai-draft-summary" aria-label={t("How the plant was drafted")}>
      <h3><Sparkles size={15} /> {t("Drafted from {tags} tags", { tags: drafted.tags })}</h3>
      {drafted.documents ? <>
        <p>{t("{loops} loops with {instruments} transmitters and valves, {equipment} pieces of equipment in {units} units and {areas} areas.", { loops: drafted.loops, instruments: drafted.instruments, equipment: drafted.equipment, units: drafted.units, areas: drafted.areas })}</p>
        <p>{t("{placed} of {loops} loops placed in their unit and area from the documents.", { placed: drafted.placed, loops: drafted.loops })}{drafted.by_model ? ` ${t("{count} placed by the language model.", { count: drafted.by_model })}` : ""}</p>
      </> : <p>{t("{loops} loops with {instruments} transmitters and valves, by their ISA-5.1 names. Without the plant's documents nothing says where they are: they go where you choose above, or draft again with Documents installed.", { loops: drafted.loops, instruments: drafted.instruments })}</p>}
      <p className="src-hint">{toCheck ? t("{count} rows to check: filter them with To check. Leaving out a unit or an area leaves out what the draft put in it.", { count: toCheck }) : t("Every row has a source. Leaving out a unit or an area leaves out what the draft put in it.")}</p>
    </section>}
    {(current.notes ?? []).length > 0 && <section className="panel ai-file-notes"><h3>{t("About the file")}</h3><ul>{current.notes!.map((text, index) => <li key={index}>{text}</li>)}</ul></section>}
    <article className="panel as-tree-panel">
      <div className="as-kinds ai-filters">{filters.map(([id, label, count]) => <button key={id || "all"} type="button" className={filter === id ? "active" : ""} aria-pressed={filter === id} onClick={() => setFilter(id)}>{label} <small>{count}</small></button>)}</div>
      <ul className="as-tree ai-tree">{tops.map((row) => renderRow(row, 0))}</ul>
    </article>
    {current.relations.length > 0 && <article className="panel">
      <h2 className="ai-section-title">{t("Relations")}</h2>
      <ul className="ai-relations">{current.relations.map((relation, index) => <li key={index} className={relation.include ? "" : "ai-out"}>
        <input type="checkbox" checked={relation.include} disabled={!isAdmin || relation.status === "skipped"} aria-label={t("Include relation")} onChange={(event) => edit({ ...current, relations: current.relations.map((item, position) => (position === index ? { ...item, include: event.target.checked } : item)) })} />
        <code>{relation.from}</code><span>{RELATION_LABELS[relation.type] ?? relation.type}</span><code>{relation.to}</code>
        <Pill status={STATUS_TONES[relation.include ? relation.status ?? "create" : "skipped"]} label={STATUS_LABELS[relation.include ? relation.status ?? "create" : "skipped"]} />
        {(relation.errors ?? []).map((text, position) => <small key={position} className="ai-error">{text}</small>)}
      </li>)}</ul>
    </article>}
  </>;
}

const RELATION_LABELS: Record<string, string> = { controls: t("controls"), measures: t("measures"), feeds: t("feeds"), downstream_of: t("is downstream of") };

function changeLabel(field: string) {
  if (field.startsWith("attributes.")) return field.slice(11);
  if (field.startsWith("signals.")) return t("signal {role}", { role: field.slice(8) });
  return ({ name: t("name"), type: t("type"), parent_id: t("place in the tree"), description: t("description") } as Record<string, string>)[field] ?? field;
}
