/**
 * `/models/<project>/<class>[/<tab>]`: one model on the tabs Analytics' algorithms have (owner,
 * 2026-10-27): Overview (what it is, no results), Inputs and outputs (what it reads and gives and
 * every block's parameters, changed here: a block's default unless the model sets its own),
 * Diagram (a preview; the editor opens in its own window), Test (one simulation with its
 * settings: a check, the studies are what run it for real), Used by (the studies of the model),
 * Versions and Settings (the simulation settings and where it is kept). Saving makes a new
 * version, with what changed. A model written as code is the one block of its diagram
 * (modelView); its code is one click away. The examples are read-only: Duplicate makes a copy.
 */
import { ComparePicker, DataTable, FolderPlaceLine, PageTabs, useAssistantPage, VersionsTab, confirmAction, type DataColumn, type VersionItem } from "@plantcraft/ui";
import { BlockEditor, ParameterField, type BlockCatalog } from "@plantcraft/ui/blockEditor";
import "@xyflow/react/dist/style.css";
import "@plantcraft/ui/blockEditor.css";
import { Code2, Copy, ExternalLink, FlaskConical, Package, Play, Save, Trash2 } from "lucide-react";
import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { ModelCompare, revisionOf, shownVersion } from "./Versions";
import { formatAgo, formatDate, t } from "./i18n";
import { href, Link, navigate } from "./nav";
import { NewModelDialog } from "./ModelsPage";
import { modelView, onSaved } from "./modelView";
import { blockPath, codePath, editorPath, modelPath, newStudyPath, runPath, type ModelTab } from "./paths";
import { FmuDialog } from "./RunDialogs";
import { ResultsPlot, RunsTable } from "./RunsPage";
import { checkDiagram, diagramParameters, scopeSignals, settingsProblem, SimulationSettings, SOLVER_NAMES } from "./SimulationSettings";
import type { BlockDiagram, Me, ModelDetail, Revision, Run, SimSettings, Study } from "./types";
import { Dialog, ErrorBox, Heading, Loading, message, Progress, reading, RunPill, StudyProgress } from "./ui";

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** Opens a model's editor in a window of its own (one window per model). */
export function openEditor(projectId: string, model: string): void {
  window.open(href(editorPath(projectId, model)), `modelcraft-editor-${projectId}-${model}`)?.focus();
}

function LastRun({ run, signals }: { run: Run; signals: string[] }) {
  const busy = run.status === "queued" || run.status === "running";
  return <section className="panel mc-model-results" aria-label={t("Results")}>
    <div className="panel-header"><div><h2>{t("Results")}</h2>
      <p><RunPill run={run} /> <Link to={runPath(run)}>{run.label || t("Simulation of {when}", { when: formatAgo(run.created_at) })}</Link>{run.summary ? ` · ${run.summary}` : ""}</p></div></div>
    {busy && (run.status === "running" && typeof run.progress === "number"
      ? <Progress value={run.progress} text={t("{n} % of the simulated time", { n: Math.round(run.progress * 100) })} />:
      <Loading text={t("Waiting in the queue…")} />)}
    {run.status === "failed" && <ul className="mc-run-messages">{run.messages.filter((item) => item.level === "error").slice(0, 5).map((item, index) => <li key={index}>{item.text}</li>)}</ul>}
    {run.status === "done" && <ResultsPlot key={run.id} run={run} others={[]} initial={signals} />}
  </section>;
}

type Port = { name: string; label: string; unit: string; detail: string };

/** What the model reads and gives: a diagram's sources and scoped signals, or the code's ports. */
export function modelPorts(diagram: BlockDiagram, catalog: BlockCatalog): { reads: Port[]; gives: Port[] } {
  const specs = Object.fromEntries(catalog.blocks.map((block) => [block.block_id, block]));
  const code = diagram.nodes.length === 1 && diagram.nodes[0].block.startsWith("modelica:") ? specs[diagram.nodes[0].block] : null;
  if (code) {
    const port = (item: (typeof code.inputs)[number]) => ({ name: item.port, label: item.label || item.port, unit: item.unit, detail: item.description !== item.label ? item.description : "" });
    return { reads: code.inputs.map(port), gives: code.outputs.map(port) };
  }
  const reads = diagram.nodes.filter((node) => specs[node.block] && specs[node.block].inputs.length === 0)
    .map((node) => ({ name: node.id, label: node.label || node.id, unit: specs[node.block].outputs[0]?.unit ?? "", detail: specs[node.block].name }));
  const gives = scopeSignals(diagram, catalog).map((signal) => {
    const [nodeId, portId] = signal.split(".");
    const node = diagram.nodes.find((item) => item.id === nodeId);
    const port = node ? specs[node.block]?.outputs.find((item) => item.port === portId) : undefined;
    return { name: signal, label: `${node?.label || nodeId} · ${port?.label || portId}`, unit: port?.unit ?? "", detail: node ? specs[node.block]?.name ?? "" : "" };
  });
  return { reads, gives };
}

export function PortsTable({ reads, gives, code }: { reads: Port[]; gives: Port[]; code: boolean }) {
  const rows = (title: string, items: Port[]) => <>
    <tr className="mc-contract-group"><th colSpan={3}>{title}</th></tr>
    {items.length ? items.map((item) => <tr key={`${title}-${item.name}`}><td><b>{item.label}</b><small className="pc-mono">{item.name}</small></td><td>{item.unit || "–"}</td><td>{item.detail}</td></tr>):
      <tr><td colSpan={3} className="muted">{t("None.")}</td></tr>}
  </>;
  return <section className="panel" aria-label={t("What it reads and gives")}>
    <h2>{t("What it reads and gives")}</h2>
    <p className="muted small">{code ? t("The real inputs and outputs of its code.") : t("It reads its sources and gives what its scopes show.")}</p>
    <table className="table mc-contract"><colgroup><col className="mc-col-name" /><col className="mc-col-unit" /><col /></colgroup>
      <tbody>{rows(code ? t("Inputs") : t("Sources"), reads)}{rows(code ? t("Outputs") : t("Shown by the scopes"), gives)}</tbody></table>
  </section>;
}

/** What the model is, as Analytics' algorithms open: no results here, the
 * Test tab and the studies have them. */
function Overview({ found, diagram, catalog, code }: { found: ModelDetail; diagram: BlockDiagram; catalog: BlockCatalog; code: boolean }) {
  const { reads, gives } = modelPorts(diagram, catalog);
  const { settings } = found;
  return <section className="panel mc-model-about">
    <h2>{t("What it is")}</h2>
    <p>{found.description || <span className="muted">{t("No description yet.")}</span>}</p>
    <dl className="mc-facts">
      <div><dt>{t("Drawn with")}</dt><dd>{code ? t("Modelica code, as one block") : t("{n} blocks", { n: diagram.nodes.length })}</dd></div>
      <div><dt>{code ? t("Inputs") : t("Sources")}</dt><dd>{reads.length ? reads.map((item) => item.label).join(", ") : t("None.")}</dd></div>
      <div><dt>{code ? t("Outputs") : t("Shown by the scopes")}</dt><dd>{gives.length ? gives.map((item) => item.label).join(", ") : t("None.")}</dd></div>
      <div><dt>{t("Simulated time")}</dt><dd>{reading(settings.stop - settings.start, "s")}</dd></div>
      <div><dt>{t("Solver")}</dt><dd>{SOLVER_NAMES[settings.solver] ?? settings.solver} · {t("step {step} s", { step: reading(settings.interval) })}</dd></div>
    </dl>
  </section>;
}

/** The bar under what a tab changes: what saving does, Undo and Save as version N (the version
 * asks what changed, as Analytics' algorithms do). */
function SaveBar({ dirty, busy, next, problem, onUndo, onSave }: { dirty: boolean; busy: boolean; next: number; problem?: string; onUndo: () => void; onSave: () => void }) {
  return <div className="panel mc-inputs-save">
    <span className="muted small">{problem || (dirty ? t("Changed: saving makes version {n}.", { n: next }) : t("Change a value to save a new version."))}</span>
    <div className="row-actions">
      <button type="button" className="button button-secondary" disabled={busy || !dirty} onClick={onUndo}>{t("Undo the changes")}</button>
      <button type="button" className="button button-primary" disabled={busy || !dirty || Boolean(problem)} onClick={onSave}><Save size={16} />{t("Save as version {n}", { n: next })}</button>
    </div>
  </div>;
}

/** Where a parameter's value comes from (defaults in cascade, block → model
 * → study): the block's default, or this model's own value over it. */
function ValueSource({ own, fallback }: { own: boolean; fallback: unknown }) {
  const shown = fallback === null || fallback === undefined || fallback === "" ? "–" : typeof fallback === "object" ? JSON.stringify(fallback) : String(fallback);
  return <small className="mc-value-source">{own ? t("This model's value (block default {value})", { value: shown }) : t("Block default")}</small>;
}

type SaveProps = { found: ModelDetail; readOnly: boolean; onSaved: (detail: ModelDetail) => void; projectId: string; model: string; next: number };

/** Saves a diagram and settings as the next version, after asking what changed. */
function useSave({ found, onSaved: saved, projectId, model }: SaveProps) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [naming, setNaming] = useState(false);
  const save = async (diagram: BlockDiagram, settings: SimSettings, name: string, note: string) => {
    setBusy(true); setError("");
    try { saved(await api.saveModel(projectId, model, diagram, settings, found.updated_at, { name, note })); setNaming(false); } catch (err) { setError(message(err)); } finally { setBusy(false); }
  };
  return { error, busy, naming, setNaming, save, setError };
}

/** What the model reads and gives, and every block's parameters, changed here without the
 * editor (as a block's inputs and outputs; saving is a new version). */
function InputsTab({ diagram, catalog, code, ...props }: SaveProps & { diagram: BlockDiagram; catalog: BlockCatalog; code: boolean }) {
  const { found, readOnly, projectId, model, next } = props;
  const [draft, setDraft] = useState(diagram);
  const { error, busy, naming, setNaming, save, setError } = useSave(props);
  const specs = Object.fromEntries(catalog.blocks.map((block) => [block.block_id, block]));
  const dirty = !same(draft, diagram);
  const setParameter = (nodeId: string, name: string, value: unknown) => setDraft({
    ...draft, nodes: draft.nodes.map((node) => (node.id === nodeId ? { ...node, parameters: { ...node.parameters, [name]: value } } : node)),
  });
  const { reads, gives } = modelPorts(diagram, catalog);
  const nodes = draft.nodes.filter((node) => (specs[node.block]?.parameters ?? []).length > 0);
  return <>
    {error && <ErrorBox text={error} />}
    <PortsTable reads={reads} gives={gives} code={code} />
    {code && <div className="notice">{t("A model written as code: its parameters are changed in the code.")} <Link to={codePath(projectId, model)}>{t("Edit the code")}</Link></div>}
    <section className="panel"><div className="panel-header"><div><h2>{t("Parameters")}</h2>
      <p>{t("Each block's default, unless this model sets its own value; a study can set another for each simulation.")}</p></div></div></section>
    {nodes.length === 0 ? <section className="panel"><p className="muted">{t("No block of this model has parameters.")}</p></section>:
      nodes.map((node) => {
        const spec = specs[node.block];
        return <section key={node.id} className="panel mc-node-parameters" aria-label={node.label || node.id}>
          <h2>{node.label || node.id} <small className="muted"><Link to={blockPath(node.block)}>{spec.name}</Link></small></h2>
          <div className="mc-node-fields">{spec.parameters.map((parameter) => <div key={parameter.name} className="mc-node-field">
            <ParameterField node={node} parameter={parameter} readOnly={readOnly || code} onSet={(value) => setParameter(node.id, parameter.name, value)} />
            <ValueSource own={node.parameters?.[parameter.name] !== undefined} fallback={parameter.default} />
          </div>)}</div>
        </section>;
      })}
    {!readOnly && !code && <SaveBar dirty={dirty} busy={busy} next={next} onUndo={() => setDraft(diagram)} onSave={() => { setError(""); setNaming(true); }} />}
    {naming && <VersionDialog next={next} busy={busy} error={error} onClose={() => setNaming(false)} onSave={(name, note) => void save(draft, found.settings, name, note)} />}
  </>;
}

/** The simulation settings and where the model is kept (a tab of its own, as
 * Analytics' algorithms; About was on Versions). Saving the settings is a new version. */
function SettingsTab({ code, ...props }: SaveProps & { code: boolean }) {
  const { found, readOnly, next } = props;
  const [settings, setSettings] = useState<SimSettings>(found.settings);
  const { error, busy, naming, setNaming, save, setError } = useSave(props);
  const dirty = !same(settings, found.settings);
  return <>
    {error && <ErrorBox text={error} />}
    <section className="panel"><SimulationSettings settings={settings} readOnly={readOnly || code} onChange={setSettings} /></section>
    {!readOnly && !code && <SaveBar dirty={dirty} busy={busy} next={next} problem={settingsProblem(settings) || undefined} onUndo={() => setSettings(found.settings)} onSave={() => { setError(""); setNaming(true); }} />}
    {naming && <VersionDialog next={next} busy={busy} error={error} onClose={() => setNaming(false)} onSave={(name, note) => void save(found.diagram, settings, name, note)} />}
    <ModelAbout found={found} />
  </>;
}

function ModelAbout({ found }: { found: ModelDetail }) {
  return <section className="panel mc-about" aria-label={t("About it")}>
    <h2>{t("About it")}</h2>
    <dl className="mc-facts">
      <div><dt>{t("Category")}</dt><dd>{found.example ? t("Examples") : found.group || t("Other")}</dd></div>
      <div><dt>{t("Class")}</dt><dd className="pc-mono">{found.model}</dd></div>
      <div><dt>{t("File")}</dt><dd className="pc-mono">{found.file}</dd></div>
      <div><dt>{t("Changed")}</dt><dd>{found.updated_at ? `${formatAgo(found.updated_at)}${found.updated_by ? ` · ${found.updated_by}` : ""}` : t("As Models ships it")}</dd></div>
    </dl>
  </section>;
}

/** One simulation with the model's settings, a test: the studies are what
 * run a model for real, over its parameters. */
function TestTab({ run, runs, signals, settings, canRun, busy, title, me, onRun, onChanged }: { run: Run | null; runs: Run[] | null; signals: string[]; settings: SimSettings; canRun: boolean; busy: boolean; title?: string; me: Me; onRun: () => void; onChanged: () => void }) {
  return <>
    <section className="panel"><div className="panel-header"><div><h2>{t("Test it")}</h2>
      <p>{t("Simulates the model once, from {start} s to {stop} s with its settings, to check it. A study is what runs it over its parameters.", { start: settings.start, stop: settings.stop })}</p></div>
      {me.can_edit && <button type="button" className="button button-primary" disabled={busy || !canRun} onClick={onRun} title={title}><Play size={16} />{t("Run the test")}</button>}
    </div></section>
    {run && <LastRun run={run} signals={signals} />}
    {runs && runs.length > 1 && <RunsTable runs={runs} me={me} onChanged={onChanged} label={t("Earlier tests")} />}
  </>;
}

/** The studies that use the model (its Used by). */
function UsedByTab({ studies, action }: { studies: Study[]; action: ReactNode }) {
  const columns: DataColumn<Study>[] = [
    { key: "name", label: t("Study"), sort: (study) => study.name, render: (study) => <><strong>{study.name}</strong>{study.description && <small>{study.description}</small>}</> },
    { key: "progress", label: t("Simulations"), sort: (study) => study.total, render: (study) => <StudyProgress study={study} /> },
    { key: "last", label: t("Last simulation"), sort: (study) => study.last_run_at ?? study.created_at, render: (study) => <span className="nowrap">{formatAgo(study.last_run_at ?? study.created_at)}<small>{study.created_by}</small></span> },
  ];
  return <>
    <section className="panel"><div className="panel-header"><div><h2>{t("Studies that use it")}</h2>
      <p>{t("Each study runs the model for the values it chooses; its page compares them.")}</p></div>{action}</div></section>
    <DataTable rows={studies} columns={columns} rowKey={(study) => study.id} label={t("Studies")} empty={t("No study of this model yet.")}
      initialSort={{ key: "last", descending: true }} onRowClick={(study) => navigate(`/studies/${encodeURIComponent(study.id)}`)} />
  </>;
}

/** A file's versions, newest first: the file as it is now, then each content a save replaced
 * (a revision keeps the old text, with who replaced it and when; round 9: Versions and About in
 * a tab of their own, as Link's blocks and algorithms). */
export function modelVersions(revisions: Revision[], now: { by?: string | null; at?: string | null; name?: string; note?: string }): VersionItem[] {
  const count = revisions.length + 1;
  return [
    { number: count, name: now.name || null, description: now.note || null, author: now.by ?? null, at: now.at ?? null, note: now.at ? null : t("As Models ships it"), current: true },
    ...revisions.map((item, index) => ({ number: count - 1 - index, name: item.version_name || null, description: item.version_note || null,
      note: t("Until {when}, replaced by {who}", { when: formatDate(item.saved_at), who: item.saved_by }) })),
  ];
}

/** The name of a new version and what changed in it, as Link's algorithms ask (round 9 M4). */
export function VersionDialog({ next, title: named, busy, error, onClose, onSave }: { next: number; title?: string; busy: boolean; error: string; onClose: () => void; onSave: (name: string, note: string) => void }) {
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const title = named ?? t("Save as version {n}", { n: next });
  // What changed is asked every time; the name is optional.
  const submit = () => { if (note.trim()) onSave(name.trim(), note.trim()); };
  return <Dialog title={title} onClose={onClose} footer={<>
    <button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button>
    <button type="button" className="button button-primary" disabled={busy || !note.trim()} onClick={submit}><Save size={16} />{busy ? t("Saving…") : title}</button>
  </>}>
    {error && <div className="notice notice-error" role="alert">{error}</div>}
    <form className="form-grid" onSubmit={(event) => { event.preventDefault(); submit(); }}>
      <label className="pc-span-all">{t("What changed")}<textarea id="mc-version-note" rows={3} value={note} maxLength={2000} autoFocus required onChange={(event) => setNote(event.target.value)} placeholder={t("e.g. A faster valve, and the tank 2 m² larger")} /></label>
      <label>{t("Version name")} <small>{t("optional")}</small><input id="mc-version-name" value={name} maxLength={120} onChange={(event) => setName(event.target.value)} placeholder={t("Faster valve")} /></label>
    </form>
  </Dialog>;
}

function VersionsOfModel({ found, revisions, projectId, model, shown }: { found: ModelDetail; revisions: Revision[] | null; projectId: string; model: string; shown: number | null }) {
  const base = modelPath(projectId, model);
  const count = (revisions?.length ?? 0) + 1;
  return <><VersionsTab
    shown={shown ?? count}
    onOpen={(number) => navigate(number === count ? base : `${base}?version=${number}`)}
    versions={revisions === null ? null : modelVersions(revisions, { by: found.updated_by, at: found.updated_at, name: found.version_name, note: found.version_note })}
    footer={<>{t("Opening an older version shows it on the other tabs, read-only; Use this version saves it again as the newest.")} <Link to={codePath(projectId, model)}>{t("Its code")}</Link></>}
  />
  {revisions && <ComparePicker numbers={Array.from({ length: count }, (_, index) => index + 1)} text={t("Tick two or three versions: each runs with the same simulation settings and their results show on one chart.")}
    onCompare={(ticked) => navigate(`${base}/compare?versions=${ticked.join(",")}`)} />}
  </>;
}

export function ModelPage({ projectId, model, tab, me }: { projectId: string; model: string; tab: ModelTab; me: Me }) {
  const [found, setFound] = useState<ModelDetail | null>(null);
  const [catalog, setCatalog] = useState<BlockCatalog | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [studies, setStudies] = useState<Study[] | null>(null);
  const [revisions, setRevisions] = useState<Revision[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [dialog, setDialog] = useState<"fmu" | "duplicate" | null>(null);
  // An older version shown read-only (?version=N, round 9 M4).
  const version = tab === "versions" || tab === "compare" || tab === "test" || tab === "used-by" ? null : shownVersion(window.location.search);
  const [old, setOld] = useState<ModelDetail | null>(null);

  const loadRuns = useCallback(() => api.runs({ project: projectId, model, kind: "simulate", limit: "50" }).then((items) => {
    // The tests are the model's own single simulations; a study's runs are on the study.
    const tests = items.filter((item) => !item.study || item.study.kind === "quick");
    setRuns(tests); setRun(tests[0] ?? null);
  }), [projectId, model]);
  const load = useCallback(async () => {
    const [detail, blocks] = await Promise.all([api.model(projectId, model), api.catalog()]);
    setFound(detail); setCatalog(blocks);
    api.revisions(projectId, detail.file).then(setRevisions).catch(() => setRevisions([]));
  }, [projectId, model]);
  useEffect(() => {
    load().catch((err) => setError(message(err)));
    loadRuns().catch(() => setRuns([]));
    api.studies({ project: projectId, model }).then(setStudies).catch(() => setStudies([]));
    return onSaved(projectId, model, () => void load().catch(() => undefined));
  }, [load, loadRuns]);
  useEffect(() => {
    setOld(null);
    if (version === null || !revisions) return;
    const revision = revisionOf(revisions, version);
    if (!revision) return;
    api.modelVersion(projectId, model, revision).then(setOld).catch((err) => setError(message(err)));
  }, [projectId, model, version, revisions]);
  // A run in the queue or running is followed until it ends.
  useEffect(() => {
    if (!run || (run.status !== "queued" && run.status !== "running")) return;
    const timer = window.setTimeout(() => { api.run(run.id).then((now) => { setRun(now); if (now.status !== run.status) void loadRuns(); }).catch(() => undefined); }, 1000);
    return () => window.clearTimeout(timer);
  }, [run]);

  const detail = old ?? found;
  const view = useMemo(() => (detail && catalog ? modelView(detail, catalog) : null), [detail, catalog]);
  const check = useMemo(() => (detail && catalog && view && !view.code ? checkDiagram(detail.diagram, catalog, detail.problems) : null), [detail, catalog, view]);
  const signals = useMemo(() => (detail && catalog ? scopeSignals(detail.diagram, catalog) : []), [detail, catalog]);
  const parameters = useMemo(() => (detail && catalog ? diagramParameters(detail.diagram, catalog) : []), [detail, catalog]);
  // Models' works for a model (app.toml: explain it, suggest a study).
  useAssistantPage(found && {
    page: "modelcraft:model", title: found.name, place: t("Models › {name}", { name: found.name }),
    context: [`Modelica model ${found.model}${found.description ? `: ${found.description}` : ""}${found.code_block ? ", written as code" : ", drawn as a block diagram"}.`,
      `Blocks: ${found.diagram.nodes.map((node) => `${node.id} (${node.block})`).join(", ") || "none"}.`,
      `Wires: ${found.diagram.edges.map((edge) => `${edge.source}.${edge.source_port} -> ${edge.target}.${edge.target_port}`).join(", ") || "none"}.`,
      `Simulation from ${found.settings.start} s to ${found.settings.stop} s, step ${found.settings.interval} s, solver ${found.settings.solver}.`].join("\n"),
  });

  if (error && !found) return <ErrorBox text={error} />;
  if (!found || !detail || !catalog || !view) return <Loading />;
  const readOnly = found.example || !me.can_edit || !found.editable || Boolean(old);
  const settingsError = settingsProblem(found.settings);
  const canRun = !old && me.can_edit && (view.code || (Boolean(check?.valid) && found.diagram.nodes.length > 0)) && !settingsError;
  const base = modelPath(projectId, model);
  const simulate = async () => {
    setBusy(true); setError("");
    try { setRun(await api.runModel(projectId, model)); void loadRuns(); } catch (err) { setError(message(err)); } finally { setBusy(false); }
  };
  const remove = async () => {
    if (!(await confirmAction(t("Delete {name}? Its simulations and studies stay in Simulations.", { name: found.name }), { confirm: t("Delete"), danger: true }))) return;
    try { await api.deleteModel(projectId, model); navigate("/models"); } catch (err) { setError(message(err)); }
  };
  const runTitle = old ? t("Back to the version in use to run it, or compare versions") : canRun ? t("Simulate with its settings") : check?.errors[0] ?? settingsError;
  const count = (revisions?.length ?? 0) + 1;
  // An older version stays shown on the tabs that show the model itself.
  const keep = old ? `?version=${version}` : "";
  const saveProps: SaveProps = { found: detail, readOnly, projectId, model, next: count + 1,
    onSaved: (saved) => { setFound(saved); api.revisions(projectId, saved.file).then(setRevisions).catch(() => undefined); } };
  const useVersion = async () => {
    if (!old?.revision || !(await confirmAction(t("Use version {number}? It is saved again as version {next}; the versions in between stay.", { number: version ?? 0, next: count + 1 }), { confirm: t("Use this version") }))) return;
    try { await api.useModelVersion(projectId, model, old.revision); navigate(base); await load(); } catch (err) { setError(message(err)); }
  };

  return <>
    <nav className="breadcrumb"><Link to="/models">{t("Models")}</Link></nav>
    <Heading eyebrow={[found.example ? t("Example") : found.group, view.code ? t("Modelica code") : t("Block diagram")].filter(Boolean).join(" · ")} title={found.name} detail={found.description || undefined}
      actions={<>
        {me.can_edit && found.editable && <button type="button" className="button button-secondary" onClick={() => setDialog("duplicate")}><Copy />{t("Duplicate")}</button>}
        {me.can_edit && <button type="button" className="button button-secondary button-icon" title={t("Export FMU")} aria-label={t("Export FMU")} onClick={() => setDialog("fmu")}><Package /></button>}
        <Link to={codePath(projectId, model)} className="button button-secondary button-icon" title={t("Modelica code")} aria-label={t("Modelica code")}><Code2 /></Link>
        {me.can_edit && !found.example && <button type="button" className="button button-danger button-icon" title={t("Delete")} aria-label={t("Delete the model")} onClick={() => void remove()}><Trash2 /></button>}
      </>} />
    <PageTabs label={t("Model")} href={href} navigate={navigate} tabs={[
      { to: `${base}${keep}`, label: t("Overview"), active: tab === "overview" },
      { to: `${base}/inputs${keep}`, label: t("Inputs and outputs"), active: tab === "inputs" },
      { to: `${base}/diagram${keep}`, label: t("Diagram"), active: tab === "diagram" },
      { to: `${base}/test`, label: t("Test"), active: tab === "test" },
      { to: `${base}/used-by`, label: studies ? t("Used by ({count})", { count: studies.length }) : t("Used by"), active: tab === "used-by" },
      { to: `${base}/versions`, label: revisions ? t("Versions ({count})", { count: revisions.length + 1 }) : t("Versions"), active: tab === "versions" || tab === "compare" },
      { to: `${base}/settings${keep}`, label: t("Settings"), active: tab === "settings" },
    ]} />
    {old && <div className="notice mc-tab-notice mc-version-notice" role="status">
      <span>{t("Version {number} of {count}, read-only: the model as it was then.", { number: version ?? 0, count })}</span>
      <span className="row-actions">
        <Link to={base} className="button button-secondary button-small">{t("Back to version {number}", { number: count })}</Link>
        {me.can_edit && !found.example && <button type="button" className="button button-primary button-small" onClick={() => void useVersion()}>{t("Use this version")}</button>}
      </span>
    </div>}
    {found.example && <div className="notice mc-tab-notice">{t("An example: it stays as Models ships it. Duplicate it to change it.")}</div>}
    {!found.editable && !view.code && <div className="notice mc-tab-notice">{t("This model has text the diagram cannot hold; change it in the code.")} {found.problems.slice(0, 3).join(" ")}</div>}
    {error && <ErrorBox text={error} />}
    <div className="mc-page mc-tab">
      <div className="mc-page-main">
        {tab === "overview" && <FolderPlaceLine kind="model" itemId={`${projectId}/${model}`} canEdit={me.can_edit} />}
        {tab === "overview" && <Overview found={detail} diagram={view.diagram} catalog={view.catalog} code={view.code} />}
        {tab === "diagram" && <section className="panel mc-page-diagram">
          <div className="panel-header"><div><h2>{t("Diagram")}</h2><p>{view.code ? t("A model written as code is one block: its inputs, outputs and parameters.") : t("Select a block to read what it does. The editor opens in its own window.")}</p></div>
            <button type="button" className="button button-secondary" onClick={() => openEditor(projectId, model)}><ExternalLink size={16} />{t("Open the editor")}</button>
          </div>
          <BlockEditor key={`${projectId}/${model}/${found.updated_at}/${old?.revision ?? 0}`} catalog={view.catalog} diagram={view.diagram} allowLoops readOnly check={check ?? undefined}
            blockHref={(blockId) => (blockId.startsWith("modelica:") ? href(codePath(projectId, model)) : href(blockPath(blockId)))} className="mc-model-preview"
            aside={<div className="mc-preview-aside"><p className="muted small">{view.code ? t("Select the block to read its inputs, outputs and parameters. Its equations are in the code.") : t("Select a block to read what it does and its parameters.")}</p>
              <Link to={codePath(projectId, model)} className="text-link small">{t("Modelica code")}</Link></div>} />
        </section>}
        {tab === "inputs" && <InputsTab key={`${found.updated_at ?? ""}/${old?.revision ?? 0}`} {...saveProps} diagram={detail.diagram} catalog={view.catalog} code={view.code} />}
        {tab === "settings" && <SettingsTab key={`${found.updated_at ?? ""}/${old?.revision ?? 0}`} {...saveProps} code={view.code} />}
        {tab === "test" && <TestTab run={run} runs={runs} signals={signals} settings={found.settings} canRun={canRun} busy={busy} title={runTitle} me={me} onRun={() => void simulate()} onChanged={() => void loadRuns()} />}
        {tab === "used-by" && (studies ? <UsedByTab studies={studies} action={me.can_edit && <Link to={newStudyPath(projectId, model)} className="button button-secondary"><FlaskConical size={16} />{t("Study it")}</Link>} /> : <Loading />)}
        {tab === "versions" && <VersionsOfModel found={found} revisions={revisions} projectId={projectId} model={model} shown={shownVersion(window.location.search)} />}
        {tab === "compare" && <ModelCompare projectId={projectId} model={model} revisions={revisions} signals={signals} canRun={me.can_edit} />}
      </div>
    </div>
    {dialog === "fmu" && <FmuDialog projectId={projectId} model={model} onClose={() => setDialog(null)} onStarted={(started) => navigate(runPath(started))} />}
    {dialog === "duplicate" && <NewModelDialog groups={[]} onClose={() => setDialog(null)} like={{ projectId, model, name: found.name, group: found.example ? "" : found.group }} />}
  </>;
}
