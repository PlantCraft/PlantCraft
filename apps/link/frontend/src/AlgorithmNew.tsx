/**
 * `/algorithms/new` (round 9): a new algorithm the way a new block is made.
 * Import an algorithm file, or fill in the form (its name, what it works on and where to start
 * from) and go on in the diagram's window; the assistant's button beside the title opens it on
 * designing an algorithm.
 */
import { chosenFolder, FolderField, putInFolder, useAssistantPage } from "@plantcraft/ui";
import { ChevronRight, FileUp, FormInput, Workflow } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "./api";
import { assistantDraft } from "./Assistant";
import { blockCatalog } from "./blockCatalog";
import { parseAlgorithmFile, type AlgorithmFile } from "./algorithmFile";
import { sketchDiagram } from "./algorithmSketch";
import { announceSaved, editorPath, newAlgorithmId } from "./algorithms";
import { t } from "./i18n";
import { href, navigate } from "./nav";
import type { Algorithm, Me, SubjectKind } from "./types";
import { ErrorBox, Heading, Link } from "./ui";

type Way = "import" | "form";

/** The editor's address for a new algorithm with what the form says. */
export function newEditorPath(start: { from: string; kind: SubjectKind; name: string; description: string; folder?: string; sketch?: string }): string {
  const path = editorPath(null, start.from || undefined);
  const query = new URLSearchParams(path.includes("?") ? path.split("?")[1] : "");
  if (!start.from) query.set("kind", start.kind);
  if (start.name.trim()) query.set("name", start.name.trim());
  if (start.description.trim()) query.set("description", start.description.trim());
  if (start.folder) query.set("folder", start.folder);
  // The diagram the assistant wrote as text (algorithmSketch.ts); a copy starts from its source.
  if (!start.from && start.sketch?.trim()) query.set("blocks", start.sketch.trim());
  return `/editor/new?${query}`;
}

function ImportStart({ taken, folder }: { taken: string[]; folder: string }) {
  const [file, setFile] = useState<AlgorithmFile | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const read = (raw: string) => { setError(""); try { setFile(parseAlgorithmFile(raw)); } catch (err) { setFile(null); setError(err instanceof Error ? err.message : String(err)); } };
  async function create() {
    if (!file) return;
    setBusy(true); setError("");
    try {
      const saved = await api.saveAlgorithm({ algorithm_id: newAlgorithmId(file.name, [...taken, "new"]), name: file.name, description: file.description, subject_kind: file.subject_kind, diagram: file.diagram, docs: file.docs, timing: file.timing, assets: [], tags: file.tags });
      await putInFolder("algorithm", saved.algorithm_id, folder);
      announceSaved(saved.algorithm_id);
      navigate(`/algorithms/${encodeURIComponent(saved.algorithm_id)}`);
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); } finally { setBusy(false); }
  }
  return <section className="panel blkn-step">
    <h2>{t("Import an algorithm file")}</h2>
    <p className="muted">{t("A JSON file in Analytics' algorithm format (plantcraft-algorithm/1), as Download the file gives it on an algorithm's page: its diagram, texts and data window. Its assets are chosen here after.")}</p>
    <label className="button button-secondary blkn-upload"><FileUp size={16} />{t("Choose a file…")}<input type="file" accept=".json,application/json" onChange={(event) => { const chosen = event.target.files?.[0]; if (chosen) chosen.text().then(read).catch((err: Error) => setError(err.message)); }} /></label>
    <label className="blkn-paste">{t("Or paste it here")}<textarea id="algn-import-text" rows={8} className="pc-mono" value={text} onChange={(event) => { setText(event.target.value); if (event.target.value.trim()) read(event.target.value); else setFile(null); }} /></label>
    {file && <p className="blkf-ok small">{t("{name}: {count} blocks. It is saved as version 1 of a new algorithm of this site.", { name: file.name, count: file.diagram.nodes.length })}</p>}
    {error && <div className="notice notice-error" role="alert">{error}</div>}
    <div className="row-actions"><button type="button" className="button button-primary" disabled={!file || busy} onClick={() => void create()}>{busy ? t("Saving…") : t("Create the algorithm")}</button></div>
  </section>;
}

/** What the assistant's card handed over (Link's "new-algorithm" work), as the form's first values. */
export function algorithmStart(draft: Record<string, unknown> | null): { name: string; description: string; kind: SubjectKind; from: string; sketch: string } {
  const kind = String(draft?.works_on ?? "");
  return {
    name: String(draft?.name ?? "").slice(0, 120),
    description: String(draft?.description ?? "").slice(0, 2000),
    kind: kind === "loop" || kind === "signal" ? kind : "asset",
    from: String(draft?.start_from ?? ""),
    sketch: String(draft?.diagram ?? "").slice(0, 4000),
  };
}

function FormStart({ algorithms, start, folder }: { algorithms: Algorithm[]; start: ReturnType<typeof algorithmStart>; folder: string }) {
  const [name, setName] = useState(start.name);
  const [description, setDescription] = useState(start.description);
  const [kind, setKind] = useState<SubjectKind>(start.kind);
  const [from, setFrom] = useState(start.from);
  const [sketch, setSketch] = useState(start.sketch);
  const [catalog, setCatalog] = useState<Awaited<ReturnType<typeof blockCatalog>> | null>(null);
  useEffect(() => { if (start.sketch) blockCatalog().then(setCatalog).catch(() => setCatalog(null)); }, [start.sketch]);
  const read = catalog && sketch.trim() ? sketchDiagram(sketch, catalog) : null;
  const source = algorithms.find((item) => item.algorithm_id === from);
  const go = () => window.open(href(newEditorPath({ from, kind: source?.subject_kind ?? kind, name, description, folder, sketch })), `linkcraft-editor-new-${Date.now()}`)?.focus();
  return <section className="panel blkn-step">
    <h2>{t("Fill in the form")}</h2>
    <p className="muted">{t("Name it, say what it works on and where to start; the blocks are then placed and wired in the diagram's window, and its first save is version 1.")}</p>
    <div className="form-grid">
      <label>{t("Name")}<input id="algn-name" value={name} maxLength={120} onChange={(event) => setName(event.target.value)} placeholder={t("Heat exchanger fouling")} /></label>
      <label>{t("Works on")}<select id="algn-kind" value={source?.subject_kind ?? kind} disabled={!!source} onChange={(event) => setKind(event.target.value as SubjectKind)}>
        <option value="asset">{t("Assets (units, equipment)")}</option><option value="loop">{t("Control loops")}</option><option value="signal">{t("Signals")}</option>
      </select></label>
      <label className="blkf-wide">{t("Description")}<textarea id="algn-description" rows={2} value={description} maxLength={2000} onChange={(event) => setDescription(event.target.value)} /></label>
      <label className="blkf-wide">{t("Start from")}<select id="algn-from" value={from} onChange={(event) => setFrom(event.target.value)}>
        <option value="">{t("An empty diagram")}</option>
        {algorithms.map((item) => <option key={item.algorithm_id} value={item.algorithm_id}>{t("A copy of {name}", { name: item.name })}</option>)}
      </select></label>
      {start.sketch && !from && <label className="blkf-wide">{t("Diagram (the assistant's blocks and wires)")}<textarea id="algn-sketch" rows={6} className="pc-mono" value={sketch} maxLength={4000} onChange={(event) => setSketch(event.target.value)} /></label>}
    </div>
    {start.sketch && !from && read && <p className={read.problems.length ? "small muted" : "blkf-ok small"}>
      {t("{blocks} blocks and {wires} wires are placed in the diagram.", { blocks: read.diagram.nodes.length, wires: read.diagram.edges.length })}
      {read.problems.length > 0 && <> {t("Left out: {items}", { items: read.problems.join("; ") })}</>}
    </p>}
    <div className="row-actions"><button type="button" className="button button-primary" onClick={go}><Workflow size={16} />{t("Continue in the diagram")}</button></div>
  </section>;
}

export function NewAlgorithmPage({ me }: { me: Me }) {
  // An algorithm the assistant proposed starts the form filled in.
  const [draft] = useState(() => assistantDraft("new-algorithm", "algorithm-variant"));
  const [way, setWay] = useState<Way | null>(draft ? "form" : null);
  const [algorithms, setAlgorithms] = useState<Algorithm[]>([]);
  const [error, setError] = useState("");
  // The folder its list showed (round 9, D14).
  const [folder, setFolder] = useState(() => chosenFolder(window.location.search));
  useEffect(() => { api.algorithms().then(setAlgorithms).catch((err: Error) => setError(err.message)); }, []);
  useAssistantPage({
    title: t("A new algorithm"), place: t("Analytics › New algorithm"), platformUrl: me.processcraft_url, page: "linkcraft:algorithm-new",
    context: t("The person is creating a new algorithm in Analytics: a diagram of blocks that judges assets, loops or signals on a cadence."),
  });
  if (!me.can_edit) return <ErrorBox text={t("Only editors make algorithms.")} />;
  const ways: Array<{ id: Way; icon: React.ReactNode; title: string; text: string }> = [
    { id: "import", icon: <FileUp size={20} />, title: t("Import a file"), text: t("An algorithm file (JSON) with its diagram, texts and data window.") },
    { id: "form", icon: <FormInput size={20} />, title: t("Fill in the form"), text: t("Its name, what it works on and where to start; then the diagram.") },
  ];
  return <>
    <nav className="breadcrumb"><Link to="/algorithms">{t("Algorithms")}</Link><ChevronRight size={12} /><span>{t("New algorithm")}</span></nav>
    <Heading title={t("New algorithm")} />
    {error && <ErrorBox text={error} />}
    <div className="pc-grid blkn-ways">{ways.map((item) => <button key={item.id} type="button" className={`panel card blkn-way${way === item.id ? " active" : ""}`} aria-pressed={way === item.id} onClick={() => setWay(item.id)}>
      <span className="blkn-way-icon">{item.icon}</span><strong>{item.title}</strong><p>{item.text}</p>
    </button>)}</div>
    {way && <FolderField kind="algorithm" value={folder} onChange={setFolder} />}
    {way === "import" && <ImportStart taken={algorithms.map((item) => item.algorithm_id)} folder={folder} />}
    {way === "form" && <FormStart algorithms={algorithms} start={algorithmStart(draft)} folder={folder} />}
  </>;
}
