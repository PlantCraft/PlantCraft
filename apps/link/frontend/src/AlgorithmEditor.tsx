/**
 * The algorithm editor, in its own window (owner, 2026-10-22: Simulink-like, the whole screen
 * for the diagram), and the read-only diagram the other pages show. Both draw the suite's
 * `BlockEditor` (@plantcraft/ui): Link gives it the blocks, the diagram, the check and the test.
 */
import "@xyflow/react/dist/style.css";
import "@plantcraft/ui/blockEditor.css";
import { AppMark, chosenFolder, confirmAction, isoOf, putInFolder, tabTitle } from "@plantcraft/ui";
import { BlockEditor, emptyDiagram, fitHeight, type BlockCatalog, type Diagram, type DiagramCheck, type DiagramTrace } from "@plantcraft/ui/blockEditor";
import { AlertTriangle, Copy, FlaskConical, LoaderCircle, Save, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { algorithmOf, announceSaved, copyName, newAlgorithmId, openEditor, SIGNAL_QUALITY, traceOfBlocks } from "./algorithms";
import { formatDate, t } from "./i18n";
import { resultLabel } from "./status";
import { href } from "./nav";
import { assetChoices } from "./AssetSettings";
import { sketchDiagram } from "./algorithmSketch";
import { CalibrateTool, DEVIATION_BLOCK } from "./Calibrate";
import { DEFAULT_TIMING, EMPTY_DOCS, type Algorithm, type AlgorithmDocs, type AlgorithmTest, type AssetChoice, type AssetTiming, type BlockResult, type Blocks, type ComputePlacement, type Me, type SubjectKind } from "./types";
import { ErrorBox, Loading, Pill } from "./ui";

let blocksCache: Promise<Blocks> | null = null;
/** The palette, read once per page load (again after a block is saved). */
export function blockCatalog(): Promise<Blocks> {
  if (!blocksCache) blocksCache = api.blocks().catch((error: unknown) => { blocksCache = null; throw error; });
  return blocksCache;
}

/** Read the palette again on next use: a block was saved, copied or deleted. */
export function forgetBlockCatalog(): void {
  blocksCache = null;
}

const blockHref = (blockId: string) => href(`/blocks/${encodeURIComponent(blockId)}`);

/** An algorithm's diagram, read-only, with what each block said in a run when given. */
/** An algorithm drawn read-only; without `height` it is as tall as fitting it to the width takes. */
/** An algorithm's diagram, read-only: the saved one, or `algorithm` as given (an older version). */
export function AlgorithmDiagram({ algorithmId, algorithm: given, blocks, trace: given_trace, height }: { algorithmId: string; algorithm?: Algorithm; blocks?: Record<string, BlockResult>; trace?: DiagramTrace | null; height?: number }) {
  const [state, setState] = useState<{ catalog: BlockCatalog; algorithm: Algorithm | undefined } | null>(null);
  const [error, setError] = useState("");
  const frame = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const element = frame.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)));
    observer.observe(element);
    return () => observer.disconnect();
  }, [state]);
  useEffect(() => {
    Promise.all([blockCatalog(), given ? Promise.resolve([given]) : api.algorithms()])
      .then(([catalog, items]) => setState({ catalog, algorithm: given ?? algorithmOf(items, algorithmId) }))
      .catch((err: Error) => setError(err.message));
  }, [algorithmId, given]);
  const trace = useMemo(() => given_trace ?? (state?.algorithm ? traceOfBlocks(state.catalog, state.algorithm.diagram.nodes, blocks) : null), [state, blocks, given_trace]);
  if (error) return <p className="muted">{error}</p>;
  if (!state) return <div className="alg-diagram alg-diagram-loading" style={{ height: height ?? 360 }}><LoaderCircle className="spin" /><span>{t("Drawing the algorithm…")}</span></div>;
  if (!state.algorithm) return <p className="muted">{t("Algorithm not found.")}</p>;
  const shown = height ?? fitHeight(state.algorithm.diagram, width);
  return <div className="alg-diagram" ref={frame} style={{ height: shown }}>
    <BlockEditor key={width ? shown : 0} catalog={state.catalog} diagram={state.algorithm.diagram} check={state.algorithm.check} trace={trace} blockHref={blockHref} />
  </div>;
}

type Draft = { algorithm_id: string; name: string; description: string; subject_kind: SubjectKind; docs: AlgorithmDocs; system: boolean; saved: boolean; timing: AssetTiming; assets: string[]; compute?: ComputePlacement; locked?: boolean; tags?: string[] };

const KIND_WORDS: Record<SubjectKind, string> = { loop: "on loops", signal: "on signals", asset: "on assets" };

/** The algorithm's own panel, beside the diagram when no block is selected: its name and what it
 * works on. Its texts, its assets and its data window are on its page, so the editor shows the
 * diagram alone (owner, 2026-10-24). */
function DocsPanel({ draft, setDraft, readOnly }: { draft: Draft; setDraft: (next: Draft) => void; readOnly: boolean }) {
  return <div className="alg-docs">
    <h3>{t("Algorithm")}</h3>
    <label>{t("Name")}<input value={draft.name} disabled={readOnly} maxLength={120} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label>
    <label>{t("Description")}<textarea rows={2} value={draft.description} disabled={readOnly} maxLength={2000} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></label>
    <label>{t("Works on")}<select value={draft.subject_kind} disabled={readOnly || draft.saved} onChange={(event) => setDraft({ ...draft, subject_kind: event.target.value as Draft["subject_kind"] })}>
      <option value="loop">{t("Control loops")}</option><option value="signal">{t("Signals")}</option><option value="asset">{t("Assets (units, equipment)")}</option>
    </select></label>
    <p className="muted small">{draft.saved
      ? t("What it is for, the assets it runs on and the data each run reads are on the algorithm's page.")
      : t("Once it is saved, its page takes what it is for, the assets it runs on and the data each run reads.")}</p>
  </div>;
}

/** Runs the diagram on one asset's window (ending now, or at a chosen time) and shows every wire. */
export function AssetTestControl({ diagram, draft, onTrace, disabled }: { diagram: Diagram; draft: Pick<Draft, "assets" | "timing">; onTrace: (test: AlgorithmTest | null) => void; disabled: string }) {
  const [choices, setChoices] = useState<AssetChoice[]>([]);
  const [assetId, setAssetId] = useState(draft.assets[0] ?? "");
  const [end, setEnd] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { assetChoices().then(setChoices).catch(() => setChoices([])); }, []);
  useEffect(() => { setAssetId((now) => now || draft.assets[0] || ""); }, [draft.assets]);
  const named = draft.assets.map((item) => choices.find((choice) => choice.id === item) ?? { id: item, name: item, path: "", kind: "", roles: [] });
  const options = named.length ? named : choices;
  async function run() {
    setRunning(true); setError("");
    try { onTrace(await api.testOnAsset(diagram, assetId, draft.timing, end ? isoOf(end) : undefined)); } catch (err) { onTrace(null); setError(err instanceof Error ? err.message : String(err)); } finally { setRunning(false); }
  }
  return <span className="alg-test">
    <select aria-label={t("Asset to test on")} value={assetId} disabled={!!disabled || !options.length} onChange={(event) => setAssetId(event.target.value)}>
      {!assetId && <option value="">{t("Choose an asset…")}</option>}
      {options.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
    </select>
    <input type="datetime-local" aria-label={t("Window ending at (empty: now)")} title={t("Window ending at (empty: now)")} value={end} disabled={!!disabled} onChange={(event) => setEnd(event.target.value)} />
    <button type="button" className="button button-secondary" title={disabled || t("Run the diagram on this asset's window, without saving")} disabled={!!disabled || running || !assetId} onClick={() => void run()}>
      {running ? <LoaderCircle size={16} className="spin" /> : <FlaskConical size={16} />}{t("Test")}
    </button>
    {error && <span className="alg-test-error" role="alert" title={error}><AlertTriangle size={14} />{t("Test failed")}</span>}
  </span>;
}

/** Runs the diagram on one loop's recent data and shows what every wire carried. */
export function TestControl({ diagram, onTrace, disabled }: { diagram: Diagram; onTrace: (test: AlgorithmTest | null) => void; disabled: string }) {
  const [loops, setLoops] = useState<Array<{ loop_id: string; name: string }>>([]);
  const [loopId, setLoopId] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { api.loops().then((items) => { setLoops(items); setLoopId((now) => now || items[0]?.loop_id || ""); }).catch(() => setLoops([])); }, []);
  async function run() {
    setRunning(true); setError("");
    try { onTrace(await api.testAlgorithm(diagram, loopId)); } catch (err) { onTrace(null); setError(err instanceof Error ? err.message : String(err)); } finally { setRunning(false); }
  }
  return <span className="alg-test">
    <select aria-label={t("Loop to test on")} value={loopId} disabled={!!disabled || !loops.length} onChange={(event) => setLoopId(event.target.value)}>
      {loops.map((item) => <option key={item.loop_id} value={item.loop_id}>{item.name || item.loop_id}</option>)}
    </select>
    <button type="button" className="button button-secondary" title={disabled || t("Run the diagram on this loop's recent data, without saving")} disabled={!!disabled || running || !loopId} onClick={() => void run()}>
      {running ? <LoaderCircle size={16} className="spin" /> : <FlaskConical size={16} />}{t("Test")}
    </button>
    {error && <span className="alg-test-error" role="alert" title={error}><AlertTriangle size={14} />{t("Test failed")}</span>}
  </span>;
}

function EditorLoaded({ me, start, catalog, taken }: { me: Me; start: { draft: Draft; diagram: Diagram; generated: AlgorithmDocs }; catalog: BlockCatalog; taken: string[] }) {
  const [draft, setDraft] = useState(start.draft);
  const [diagram, setDiagram] = useState(start.diagram);
  const [check, setCheck] = useState<DiagramCheck | null>(null);
  const [test, setTest] = useState<AlgorithmTest | null>(null);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const savedState = useRef(JSON.stringify({ draft: start.draft, diagram: start.diagram }));
  const readOnly = draft.system || draft.locked || !me.can_edit;
  const dirty = !draft.saved || JSON.stringify({ draft, diagram }) !== savedState.current;

  // The check follows every edit (a moment after it).
  useEffect(() => {
    const timer = window.setTimeout(() => {
      api.checkAlgorithm(diagram).then(setCheck).catch(() => undefined);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [diagram]);
  useEffect(() => { document.title = tabTitle("linkcraft", `${draft.name || t("New algorithm")} · ${t("Algorithm editor")}`); }, [draft.name]);
  useEffect(() => {
    if (!dirty) return undefined;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  function edit(next: Diagram) { setDiagram(next); setTest(null); }

  async function save() {
    setSaving(true); setNotice(null);
    const algorithmId = draft.saved ? draft.algorithm_id : newAlgorithmId(draft.name, taken);
    try {
      const saved = await api.saveAlgorithm({ algorithm_id: algorithmId, name: draft.name.trim(), description: draft.description, subject_kind: draft.subject_kind, diagram, docs: draft.docs, timing: draft.timing, assets: draft.assets, ...(draft.compute ? { compute: draft.compute } : {}), ...(draft.saved ? {} : { tags: draft.tags ?? [] }) });
      // A new algorithm goes in the folder its form chose (round 9, D14).
      if (!draft.saved) await putInFolder("algorithm", saved.algorithm_id, chosenFolder(window.location.search));
      const next = { ...draft, algorithm_id: saved.algorithm_id, name: saved.name, saved: true };
      setDraft(next);
      savedState.current = JSON.stringify({ draft: next, diagram });
      if (!draft.saved) window.history.replaceState({}, "", href(`/editor/${encodeURIComponent(saved.algorithm_id)}`));
      announceSaved(saved.algorithm_id);
      setNotice({ tone: "ok", text: draft.subject_kind === "asset"
        ? t("Saved {when}. Its assets run this version from their next cycle.", { when: formatDate(saved.updated_at ?? new Date().toISOString()) })
        : t("Saved {when}. Its monitors and loops run this version from now on.", { when: formatDate(saved.updated_at ?? new Date().toISOString()) }) });
    } catch (err) {
      setNotice({ tone: "error", text: err instanceof Error ? err.message : String(err) });
    } finally { setSaving(false); }
  }

  const trace: DiagramTrace | null = test?.trace ?? null;
  const testDisabled = draft.subject_kind === "signal" ? t("A signal algorithm is tested by its runs, on Signal quality.") : check && !check.valid ? t("Fix the problems first.") : "";
  const kindLabel = t(KIND_WORDS[draft.subject_kind]);
  const verdict = test?.summary?.verdict;
  return <div className="alg-window">
    <header className="alg-window-bar">
      <a href={href(draft.saved ? `/algorithms/${encodeURIComponent(draft.algorithm_id)}` : "/algorithms")} className="alg-window-brand" title={t("Analytics' Algorithms page")}><AppMark app="linkcraft" size={22} /><span>{t("Analytics")}</span></a>
      <span className="alg-window-title"><b>{draft.name || t("New algorithm")}</b><small>{[draft.system ? t("PlantCraft's algorithm, read-only") : draft.locked ? t("Read-only: another group answers for it") : draft.saved ? t("Site algorithm") : t("Not saved yet"), kindLabel, draft.saved && dirty ? t("changed") : ""].filter(Boolean).join(" · ")}</small></span>
      {test?.asset_id && verdict && <span className="alg-window-test"><Pill status={verdict.status === "bad" ? "alarm" : verdict.status} label={t("Test: {status}", { status: resultLabel(verdict.status) })} /><small>{t("{asset}, {start} to {end}", { asset: test.asset_name ?? test.asset_id, start: formatDate(test.summary?.window?.start), end: formatDate(test.summary?.window?.end) })}</small></span>}
      {test?.summary && !test.asset_id && <span className="alg-window-test"><Pill status={test.summary.status ?? "unknown"} label={test.summary.health !== null && test.summary.health !== undefined ? t("Test: health {value} %", { value: Math.round(test.summary.health) }) : t("Test ran")} /><small>{t("{loop}, {start} to {end}", { loop: test.loop_id ?? "", start: formatDate(test.source_start), end: formatDate(test.source_end) })}</small></span>}
      <span className="alg-window-actions">
        {draft.subject_kind === "asset"
          ? <AssetTestControl diagram={diagram} draft={draft} onTrace={setTest} disabled={check && !check.valid ? t("Fix the problems first.") : ""} />
          : <TestControl diagram={diagram} onTrace={setTest} disabled={testDisabled} />}
        {me.can_edit && draft.saved && <button type="button" className="button button-secondary" onClick={() => openEditor(null, draft.algorithm_id)}><Copy size={16} />{t("Duplicate")}</button>}
        {!readOnly && <button type="button" className="button button-primary" disabled={saving || !draft.name.trim() || !dirty || (check ? !check.valid : true)} title={check && !check.valid ? t("Fix the problems first.") : undefined} onClick={() => void save()}>
          {saving ? <LoaderCircle size={16} className="spin" /> : <Save size={16} />}{t("Save")}
        </button>}
        <button type="button" className="icon-button" aria-label={t("Close the window")} title={t("Close the window")} onClick={async () => { if (!dirty || await confirmAction(t("Close without saving the changes?"), { confirm: t("Close without saving"), danger: true })) window.close(); }}><X size={18} /></button>
      </span>
    </header>
    {notice && <div className={`alg-window-notice notice notice-${notice.tone === "ok" ? "ok" : "error"}`} role={notice.tone === "error" ? "alert" : "status"}>{notice.text}<button type="button" className="icon-button" aria-label={t("Dismiss")} onClick={() => setNotice(null)}><X size={14} /></button></div>}
    {draft.locked && me.can_edit && <div className="alg-window-notice notice">{t("A group answers for this algorithm and you are not in it: it opens read-only. Duplicate it to change a copy.")}</div>}
    {draft.system && me.can_edit && <div className="alg-window-notice notice">{t("PlantCraft's own algorithms are read-only, so every site starts from the same reference. Duplicate it to change a copy.")}</div>}
    <div className="alg-window-editor">
      <BlockEditor catalog={catalog} diagram={diagram} onChange={readOnly ? undefined : edit} check={check} trace={trace} blockHref={blockHref}
        inspectorTools={(node) => node.block === DEVIATION_BLOCK && draft.subject_kind === "asset"
          ? <CalibrateTool node={node} diagram={diagram} timing={draft.timing} assets={draft.assets} readOnly={readOnly} disabled={check && !check.valid ? t("Fix the problems first.") : ""} onCalibrated={edit} />
          : null}
        aside={<DocsPanel draft={draft} setDraft={setDraft} readOnly={readOnly} />} />
    </div>
  </div>;
}

/**
 * `/editor/<id>`, `/editor/new`, `/editor/new?from=<id>` and `/editor/new?model=<model id>` (what
 * "Publish to Link" in Models opens): the editor's own window.
 */
export function EditorWindow({ algorithmId, me }: { algorithmId: string; me: Me }) {
  const [state, setState] = useState<{ catalog: BlockCatalog; start: { draft: Draft; diagram: Diagram; generated: AlgorithmDocs }; taken: string[] } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const model = algorithmId === "new" ? new URLSearchParams(window.location.search).get("model") : null;
    Promise.all([blockCatalog(), api.algorithms(), model ? api.modelStarter(model) : Promise.resolve(null)]).then(([catalog, items, starter]) => {
      const taken = items.map((item) => item.algorithm_id);
      if (algorithmId !== "new") {
        const found = algorithmOf(items, algorithmId);
        if (!found) { setError(t("Algorithm not found.")); return; }
        setState({ catalog, taken, start: { diagram: found.diagram, generated: found.docs_generated, draft: { algorithm_id: found.algorithm_id, name: found.name, description: found.description, subject_kind: found.subject_kind, docs: { ...EMPTY_DOCS, ...found.docs }, system: found.system, saved: true, timing: found.timing ?? DEFAULT_TIMING, assets: found.assets ?? [], compute: found.compute, locked: !found.system && !found.editable } } });
        return;
      }
      if (starter) {
        setState({ catalog, taken, start: { diagram: starter.diagram, generated: EMPTY_DOCS, draft: { algorithm_id: "", name: starter.name, description: starter.description, subject_kind: "asset", docs: EMPTY_DOCS, system: false, saved: false, timing: starter.timing, assets: [] } } });
        return;
      }
      const from = algorithmOf(items, new URLSearchParams(window.location.search).get("from"));
      const query = new URLSearchParams(window.location.search);
      const asked = query.get("kind");
      // The New algorithm form's name and description (round 9).
      const named = query.get("name")?.slice(0, 120) ?? "";
      const described = query.get("description")?.slice(0, 2000) ?? "";
      // The assistant's diagram, written as text (algorithmSketch.ts).
      const sketch = query.get("blocks")?.slice(0, 4000) ?? "";
      const kind: SubjectKind = asked === "signal" || asked === "asset" ? asked : "loop";
      setState({ catalog, taken, start: {
        diagram: from ? structuredClone(from.diagram) : sketch ? sketchDiagram(sketch, catalog).diagram : emptyDiagram(),
        generated: from?.docs_generated ?? EMPTY_DOCS,
        draft: { algorithm_id: "", name: named || (from ? copyName(from.name) : ""), description: described || (from?.description ?? ""), subject_kind: from?.subject_kind ?? kind, docs: from ? { ...EMPTY_DOCS, ...from.docs } : EMPTY_DOCS, system: false, saved: false, timing: from?.timing ?? DEFAULT_TIMING, assets: from?.assets ?? [], compute: from?.compute, tags: from?.tags ?? [] },
      } });
    }).catch((err: Error) => setError(err.message));
  }, [algorithmId]);
  if (error) return <div className="alg-window alg-window-state"><ErrorBox text={error} /></div>;
  if (!state) return <div className="alg-window alg-window-state"><Loading /></div>;
  return <EditorLoaded me={me} catalog={state.catalog} start={state.start} taken={state.taken} />;
}

export { SIGNAL_QUALITY };
