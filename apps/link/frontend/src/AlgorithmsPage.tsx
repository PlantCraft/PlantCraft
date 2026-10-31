/**
 * Algorithms: one list, PlantCraft's own and the site's together, each a block
 * diagram that judges loops, signals or assets on a schedule, with its tags, author, owner,
 * version and how many assets use it. The list opens an algorithm's page, which has a block's tabs
 * and, like a block's, Duplicate, Download the file and Delete on top and New version on its
 * Versions tab (owner D19, 2026-10-26; round 10): its texts, its diagram, its parameters and its
 * data window change in one form, tested there, and each save is a new version with its own name
 * and what changed. PlantCraft's own show a lock there; Duplicate makes one's own. Any version opens on the page (`?version=N`). A responsible
 * group, when set, is the only one that edits it. Versions and "About it" are a tab of their own.
 */
import { chosenFolder, comparedVersions, confirmAction, DataTable, Dialog, FolderColumn, FolderPlaceLine, inFolder, isoOf, MultiSelect, NO_FOLDER, PageTabs, rememberFolder, renderMarkdown, useAssistantPage, useFolders, VersionLock, VersionsTab, type DataColumn } from "@plantcraft/ui";
import { BlockEditor, ParameterField, setParameter, type BlockCatalog, type Diagram, type DiagramCheck, type DiagramNode } from "@plantcraft/ui/blockEditor";
import { ChevronRight, Copy, Download, Factory, FlaskConical, PenLine, Plus, Save, Trash2 } from "lucide-react";
import { downloadAlgorithmFile } from "./algorithmFile";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "./api";
import { AlgorithmDiagram, AssetTestControl, blockCatalog, TestControl } from "./AlgorithmEditor";
import { CalibrateTool, DEVIATION_BLOCK } from "./Calibrate";
import { assetChoices, AssetPicker, AssetRuns, AssetTypePicker, TimingFields } from "./AssetSettings";
import { announceSaved, onSaved, openEditor, SIGNAL_QUALITY, tagOptions, withTags } from "./algorithms";
import { LinkAssistant } from "./Assistant";
import { algorithmComparison, ComparePicker, CompareView } from "./Compare";
import { formatDate, t } from "./i18n";
import { href, navigate } from "./nav";
import { resultLabel, statusLabel } from "./status";
import { DEFAULT_TIMING, DOC_FIELDS, EMPTY_DOCS, type Algorithm, type AlgorithmOutput, type AlgorithmTest, type AlgorithmUsage, type AlgorithmVersion, type AssetChoice, type AssetTiming, type CatalogBlock, type ComputeOffer, type ComputePlacement, type Me, type ModelExample, type UserGroup } from "./types";
import { ErrorBox, Health, Heading, Link, Loading, Pill } from "./ui";
import { KIND_LABEL, Tags } from "./AlgorithmList";

export { AlgorithmsPage } from "./AlgorithmList";

export const ALGORITHM_TABS = ["inputs", "diagram", "test", "used-by", "versions", "settings", "edit"] as const;
export type AlgorithmTab = "overview" | (typeof ALGORITHM_TABS)[number] | "compare";

/** `/algorithms/<id>/<tab>` -> the algorithm id and the tab (algorithm ids never hold slashes). */
export function algorithmRoute(id: string): { algorithmId: string; tab: AlgorithmTab } {
  const [algorithmId, tab] = id.split("/");
  if (tab === "compare") return { algorithmId, tab: "compare" };
  return { algorithmId, tab: (ALGORITHM_TABS as readonly string[]).includes(tab ?? "") ? (tab as AlgorithmTab) : "overview" };
}

/** Saves the algorithm with a change (its texts, its diagram, its parameters, its assets): a new
 * version, with its own name and what changed when given. */
async function saveChanged(algorithm: Algorithm, change: Partial<Pick<Algorithm, "name" | "description" | "docs" | "diagram" | "timing" | "assets" | "asset_types" | "compute">>, note?: { name: string; description: string }): Promise<Algorithm> {
  const next = { ...algorithm, ...change };
  const saved = await api.saveAlgorithm({
    algorithm_id: next.algorithm_id, name: next.name.trim(), description: next.description, subject_kind: next.subject_kind,
    diagram: next.diagram, docs: next.docs, timing: next.timing ?? DEFAULT_TIMING, assets: next.assets ?? [],
    ...(next.compute ? { compute: next.compute } : {}),
    ...(change.asset_types ? { asset_types: change.asset_types } : {}),
    ...(note ? { version_name: note.name, version_note: note.description } : {}),
  });
  announceSaved(saved.algorithm_id);
  return saved;
}

/** Who answers for an algorithm, its tags and the group whose members edit it (not a version). */
function Stewardship({ algorithm, me, onSaved: saved }: { algorithm: Algorithm; me: Me; onSaved: (next: Algorithm) => void }) {
  const editable = algorithm.editable && !algorithm.system;
  const [editing, setEditing] = useState(false);
  const [people, setPeople] = useState<Array<{ username: string; name: string }>>([]);
  const [groups, setGroups] = useState<UserGroup[]>([]);
  const [owner, setOwner] = useState(algorithm.owner);
  const [tags, setTags] = useState((algorithm.tags ?? []).join(", "));
  const [group, setGroup] = useState(algorithm.group?.id ?? "");
  const [note, setNote] = useState("");
  useEffect(() => {
    if (!editable || !editing) return;
    api.blockPeople().then(setPeople).catch(() => setPeople([]));
    api.userGroups().then(setGroups).catch(() => setGroups([]));
  }, [editable, editing]);
  async function save() {
    try {
      const person = people.find((item) => item.username === owner);
      const next = await api.updateAlgorithm(algorithm.algorithm_id, { owner, owner_name: person?.name ?? owner, tags: tags.split(",").map((item) => item.trim()).filter(Boolean), group_id: group });
      setNote(t("Saved."));
      setEditing(false);
      saved(next);
    } catch (err) { setNote(err instanceof Error ? err.message : String(err)); }
  }
  return <section className="panel alg-who">
    <div className="panel-header"><div><h2>{t("About it")}</h2></div>
      {editable && !editing && <button type="button" className="button button-secondary button-small" onClick={() => setEditing(true)}>{t("Change")}</button>}
    </div>
    <dl>
      <dt>{t("Author")}</dt><dd>{algorithm.author || "—"}</dd>
      <dt>{t("Owner")}</dt><dd>{editing
        ? <select id="alg-owner" value={owner} onChange={(event) => setOwner(event.target.value)}>
          {!people.some((item) => item.username === owner) && <option value={owner}>{algorithm.owner_name || owner}</option>}
          {people.map((item) => <option key={item.username} value={item.username}>{item.name}</option>)}
        </select>
        : algorithm.owner_name || "—"}</dd>
      <dt>{t("Group")}</dt><dd>{editing
        ? <select id="alg-group" value={group} onChange={(event) => setGroup(event.target.value)}>
          <option value="">{t("None: every editor")}</option>
          {group && !groups.some((item) => item.id === group) && <option value={group}>{algorithm.group?.name ?? group}</option>}
          {groups.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
        : algorithm.group?.name ?? (algorithm.system ? t("None: read-only") : t("None: every editor"))}</dd>
      <dt>{t("Works on")}</dt><dd>{t(KIND_LABEL[algorithm.subject_kind])}</dd>
      <dt>{t("Labels")}</dt><dd>{editing
        ? <input id="alg-tags" value={tags} onChange={(event) => setTags(event.target.value)} placeholder={t("control loop, data quality, digital twin")} />
        : <Tags tags={algorithm.tags ?? []} />}</dd>
    </dl>
    {editing && <div className="row-actions"><button type="button" className="button button-secondary button-small" onClick={() => void save()}>{t("Save owner, group and labels")}</button><button type="button" className="button button-secondary button-small" onClick={() => setEditing(false)}>{t("Cancel")}</button></div>}
    {note && <small className="muted">{note}</small>}
    {!editable && !algorithm.system && me.can_edit && <p className="muted small">{t("The group {name} answers for it: its members edit it; duplicate it to change a copy.", { name: algorithm.group?.name ?? "" })}</p>}
    {algorithm.system && me.can_edit && <p className="muted small">{t("PlantCraft's own algorithms are read-only: duplicate one to change a copy.")}</p>}
  </section>;
}

const SIZE_TEXT: Record<ComputePlacement["size"], string> = {
  small: "Small (1 CPU, 1 GB)",
  medium: "Medium (2 CPUs, 4 GB)",
  large: "Large (4 CPUs, 16 GB)",
};
const DEFAULT_PLACEMENT: ComputePlacement = { environment: "standard", size: "small" };

/** Where the algorithm's runs go on the suite's compute workers: the environment (the executor
 * image with the packages it needs) and the size (CPUs and memory). A change is a new version. */
function WhereItRuns({ algorithm, onSaved: saved }: { algorithm: Algorithm; onSaved: (next: Algorithm) => void }) {
  const editable = algorithm.editable && !algorithm.system;
  const current = algorithm.compute ?? DEFAULT_PLACEMENT;
  const [editing, setEditing] = useState(false);
  const [offer, setOffer] = useState<ComputeOffer | null>(null);
  const [environment, setEnvironment] = useState(current.environment);
  const [size, setSize] = useState<ComputePlacement["size"]>(current.size);
  const [note, setNote] = useState("");
  useEffect(() => { api.computeOffer().then(setOffer).catch(() => setOffer(null)); }, []);
  const environments = [...new Set(["standard", current.environment, ...(offer?.environments ?? [])])];
  const offered = (offer?.environments ?? []).includes(current.environment);
  const roomy = (offer?.sizes ?? []).includes(current.size);
  async function save() {
    try {
      const next = await saveChanged(algorithm, { compute: { environment, size } }, { name: t("Runs in {environment}, size {size}", { environment, size: t(SIZE_TEXT[size]) }), description: "" });
      setNote(t("Saved."));
      setEditing(false);
      saved(next);
    } catch (err) { setNote(err instanceof Error ? err.message : String(err)); }
  }
  return <section className="panel alg-who">
    <div className="panel-header"><div><h2>{t("Where it runs")}</h2></div>
      {editable && !editing && <button type="button" className="button button-secondary button-small" onClick={() => setEditing(true)}>{t("Change")}</button>}
    </div>
    <dl>
      <dt>{t("Environment")}</dt><dd>{editing
        ? <select id="alg-environment" value={environment} onChange={(event) => setEnvironment(event.target.value)}>
          {environments.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
        : current.environment}</dd>
      <dt>{t("Size")}</dt><dd>{editing
        ? <select id="alg-size" value={size} onChange={(event) => setSize(event.target.value as ComputePlacement["size"])}>
          {(Object.keys(SIZE_TEXT) as ComputePlacement["size"][]).map((item) => <option key={item} value={item}>{t(SIZE_TEXT[item])}</option>)}
        </select>
        : t(SIZE_TEXT[current.size])}</dd>
    </dl>
    {editing && <div className="row-actions"><button type="button" className="button button-secondary button-small" onClick={() => void save()}>{t("Save where it runs")}</button><button type="button" className="button button-secondary button-small" onClick={() => setEditing(false)}>{t("Cancel")}</button></div>}
    {note && <small className="muted">{note}</small>}
    {offer?.suite && offer.workers > 0 && (!offered || !roomy) && <p className="muted small">{t("No compute worker online offers this now: its runs wait until one does.")}</p>}
    <p className="muted small">{t("Runs go only to a compute worker with this environment and room for this size. Settings › Compute lists the workers.")}</p>
  </section>;
}

/** A version as the list shows it: its own name and note, else the algorithm's name then. */
export function algorithmVersionItem(item: AlgorithmVersion) {
  return { number: item.version, name: item.version_name || item.name, description: item.version_note || item.description, author: item.saved_by, at: item.saved_at, current: item.current };
}

/** Every saved version, newest first, in their own tab like a block's. Opening one shows the
 * page at that version; saving always makes a new version. */
function VersionsOfAlgorithm({ algorithm, me, shown, newVersion, onShow, onSaved: saved }: { algorithm: Algorithm; me: Me; shown: number; newVersion: string | null; onShow: (version: number) => void; onSaved: (next: Algorithm) => void }) {
  const [versions, setVersions] = useState<AlgorithmVersion[] | null>(null);
  useEffect(() => { api.algorithmVersions(algorithm.algorithm_id).then(setVersions).catch(() => setVersions([])); }, [algorithm.algorithm_id, algorithm.version]);
  return <VersionsTab
    versions={versions && versions.map(algorithmVersionItem)}
    shown={shown}
    onOpen={onShow}
    actions={newVersion ? <Link to={newVersion} className="button button-primary"><PenLine size={16} />{t("New version")}</Link>
      : algorithm.system ? <VersionLock>{t("Ships with PlantCraft: no new version here")}</VersionLock> : null}
    footer={algorithm.system ? t("PlantCraft's own algorithms change with PlantCraft itself. Duplicate it to make an algorithm of this site from it.")
      : t("The monitors run the version in use, the newest. Opening an older one shows the page at that version; Use this version saves it again as the newest.")} />;
}

/** Where an algorithm is used: the loops it works on and its schedules. */
function Usage({ algorithmId }: { algorithmId: string }) {
  const [usage, setUsage] = useState<AlgorithmUsage | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.algorithmUsage(algorithmId).then(setUsage).catch((err: Error) => setError(err.message)); }, [algorithmId]);
  if (error) return <p className="muted">{error}</p>;
  if (!usage) return <Loading />;
  const { subjects } = usage;
  return <div className="panel used-by">
    <p>{subjects.every
      ? t("Every active signal: {count} today.", { count: subjects.count })
      : subjects.count ? t("{count} loops use it.", { count: subjects.count }) : t("No loop uses it yet: choose it on a loop's page, or in the asset's record in PlantCraft.")}</p>
    {!!subjects.items.length && <ul className="alg-used">{subjects.items.slice(0, 12).map((item) => <li key={item.id}>
      <Link to={item.path}><b>{item.name}</b><small>{item.caption}</small></Link>
      <Pill status={item.status} label={statusLabel(item.status)} /><Health value={item.health} />
    </li>)}</ul>}
    {subjects.items.length > 12 && <p className="muted small">{t("And {count} more.", { count: subjects.items.length - 12 })}</p>}
  </div>;
}

/** The schedules that run an algorithm. */
function Schedules({ algorithmId }: { algorithmId: string }) {
  const [usage, setUsage] = useState<AlgorithmUsage | null>(null);
  useEffect(() => { api.algorithmUsage(algorithmId).then(setUsage).catch(() => setUsage(null)); }, [algorithmId]);
  if (!usage) return null;
  return <section className="panel"><div className="panel-header"><div><h2>{t("Monitors")}</h2></div></div>
    {usage.schedules.length
      ? <ul className="alg-schedules">{usage.schedules.map((item) => <li key={item.schedule_id}><Link to={`/schedules/${encodeURIComponent(item.schedule_id)}`}>{item.name}</Link></li>)}</ul>
      : <p className="muted">{t("No monitor runs it yet.")} <Link to="/schedules">{t("Monitors")}</Link></p>}
  </section>;
}

type BlockSpecs = Record<string, CatalogBlock>;
const nodeName = (node: DiagramNode, specs: BlockSpecs) => node.label || specs[node.block]?.name || node.block;

/** What the algorithm reads from its subject and what it gives back, from its diagram. */
function Contract({ algorithm, specs }: { algorithm: Algorithm; specs: BlockSpecs }) {
  const nodes = algorithm.diagram.nodes;
  const reads = nodes.filter((node) => node.block.startsWith("input."));
  const gives = nodes.filter((node) => node.block.startsWith("output."));
  const recorded = nodes.filter((node) => (node.record ?? []).length);
  const where = (node: DiagramNode) => {
    const values = node.parameters ?? {};
    if (values.signal) return t("signal {id}", { id: String(values.signal) });
    const role = String(values.role ?? specs[node.block]?.parameters.find((item) => item.name === "role")?.default ?? "—");
    return values.asset ? t("role {role} of {asset}", { role, asset: String(values.asset) }) : t("role {role}", { role });
  };
  const what = (node: DiagramNode) => {
    const values = node.parameters ?? {};
    return String(values.name ?? values.text ?? specs[node.block]?.summary ?? "");
  };
  return <section className="panel"><div className="panel-header"><div><h2>{t("What it reads and gives")}</h2><p>{t("From its diagram: what each run reads from the asset or loop, and what it writes back.")}</p></div></div>
    <div className="blk-table-wrap"><table className="table blk-contract">
      <colgroup><col className="blk-col-name" /><col className="blk-col-type" /><col /></colgroup>
      <thead><tr><th>{t("Block")}</th><th>{t("Type")}</th><th>{t("What")}</th></tr></thead>
      {reads.length > 0 && <tbody><tr className="blk-group"><th colSpan={3} scope="colgroup">{t("Reads")}</th></tr>
        {reads.map((node) => <tr key={node.id}><td><b>{nodeName(node, specs)}</b><small className="pc-mono">{node.id}</small></td><td>{specs[node.block]?.name ?? node.block}</td><td>{where(node)}</td></tr>)}</tbody>}
      {gives.length > 0 && <tbody><tr className="blk-group"><th colSpan={3} scope="colgroup">{t("Gives")}</th></tr>
        {gives.map((node) => <tr key={node.id}><td><b>{nodeName(node, specs)}</b><small className="pc-mono">{node.id}</small></td><td>{specs[node.block]?.name ?? node.block}</td><td>{what(node)}</td></tr>)}</tbody>}
      {recorded.length > 0 && <tbody><tr className="blk-group"><th colSpan={3} scope="colgroup">{t("Recorded in the Historian")}</th></tr>
        {recorded.map((node) => <tr key={node.id}><td><b>{nodeName(node, specs)}</b><small className="pc-mono">{node.id}</small></td><td>{specs[node.block]?.name ?? node.block}</td><td>{(node.record ?? []).map((port) => specs[node.block]?.outputs.find((item) => item.port === port)?.label ?? port).join(", ")}</td></tr>)}</tbody>}
    </table></div>
  </section>;
}

/** What it is for: the texts people wrote, or the ones the diagram gives. Edit changes them. */
function Texts({ read }: { read: Algorithm }) {
  return <section className="panel alg-page-docs">
    <div className="panel-header"><div><h2>{t("What it is for")}</h2><p>{t("Written by people where they did; generated from the diagram where not. The assistant reads the same text.")}</p></div></div>
    {read.description && <p>{read.description}</p>}
    <div className="alg-doc-list">{DOC_FIELDS.map((field) => {
      const written = read.docs[field];
      const text = written || read.docs_generated[field];
      if (!text) return null;
      return <div key={field} className="alg-doc"><h3>{t(DOC_TITLES[field])}{!written && <span className="tag">{t("generated")}</span>}</h3><div className="alg-doc-text">{renderMarkdown(text)}</div></div>;
    })}</div>
  </section>;
}

/** A parameter's value as the list shows it: the block's own value, else its default. */
function valueText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? t("yes") : t("no");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** The blocks that have parameters, in the diagram's order. */
// The input and output blocks' settings (which role, which name) are what it reads and gives,
// listed above; here only the calculation's own (round 9: the list was too long).
const withParameters = (diagram: Diagram, specs: BlockSpecs) => diagram.nodes.filter((node) => !/^(input|output)\./.test(node.block) && (specs[node.block]?.parameters ?? []).length);

/** The algorithm's contract as a list, like a block's: what it reads and gives, the data window
 * and every block's parameters with their values. Changing them is New version. */
function InputsTab({ algorithm, read, specs, me, editable, newVersion, onSaved: saved }: { algorithm: Algorithm; read: Algorithm; specs: BlockSpecs; me: Me; editable: boolean; newVersion: string | null; onSaved: (next: Algorithm) => void }) {
  // Like a block's: its parameters change right here, and saving them is the
  // next version with what changed; inputs and outputs change in New version (the diagram).
  const [diagram, setDiagram] = useState(read.diagram);
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const nodes = withParameters(diagram, specs);
  const timing = read.timing ?? DEFAULT_TIMING;
  const changed = JSON.stringify(diagram) !== JSON.stringify(read.diagram);
  async function save(name: string, description: string) {
    setBusy(true); setError("");
    try { saved(await saveChanged(algorithm, { diagram }, { name, description })); setSaving(false); } catch (err) { setError(err instanceof Error ? err.message : String(err)); } finally { setBusy(false); }
  }
  return <>
    <Contract algorithm={read} specs={specs} />
    {newVersion && <div className="row-actions"><Link to={newVersion} className="button button-secondary"><PenLine size={16} />{t("Change inputs and outputs in a new version")}</Link></div>}
    {read.subject_kind === "asset" && <section className="panel"><div className="panel-header"><div><h2>{t("The data each run reads")}</h2></div></div>
      <TimingFields timing={timing} disabled onChange={() => undefined} />
    </section>}
    <section className="panel"><div className="panel-header"><div><h2>{t("Parameters")}</h2><p>{editable ? t("Each block's value for this algorithm: change one and save it as a new version. A value left as it is follows the block's default.") : t("Each block's settings in this version: its own value, or the block's default.")}</p></div></div>
      {!nodes.length ? <p className="muted">{t("No block of this algorithm has parameters.")}</p>
        : editable ? nodes.map((node) => <div key={node.id} className="blkf-row alg-node-parameters">
          <h3>{nodeName(node, specs)} <small className="muted"><Link to={`/blocks/${encodeURIComponent(node.block)}`}>{specs[node.block]?.name ?? node.block}</Link> · <span className="pc-mono">{node.id}</span></small></h3>
          <div className="alg-node-fields">{specs[node.block].parameters.map((parameter) => <ParameterField key={parameter.name} node={node} parameter={parameter} readOnly={false}
            onSet={(value) => setDiagram((now) => setParameter(now, node.id, parameter.name, value))} />)}</div>
        </div>)
        : <div className="blk-table-wrap"><table className="table blk-contract alg-parameters">
          <thead><tr><th>{t("Parameter")}</th><th>{t("Value")}</th><th>{t("Description")}</th></tr></thead>
          {nodes.map((node) => <tbody key={node.id}>
            <tr className="blk-group"><th colSpan={3} scope="colgroup">{nodeName(node, specs)} <small className="muted"><Link to={`/blocks/${encodeURIComponent(node.block)}`}>{specs[node.block]?.name ?? node.block}</Link></small></th></tr>
            {specs[node.block].parameters.map((parameter) => {
              const own = node.parameters?.[parameter.name];
              return <tr key={parameter.name}>
                <td><b>{parameter.title || parameter.name}</b><small className="pc-mono">{parameter.name}</small></td>
                <td className="pc-mono">{valueText(own ?? parameter.default)}{parameter.unit ? ` ${parameter.unit}` : ""}{own === undefined && <small className="muted"> {t("default")}</small>}</td>
                <td>{parameter.description ?? ""}</td>
              </tr>;
            })}
          </tbody>)}
        </table></div>}
    </section>
    {editable && nodes.length > 0 && <div className="blkf-bar panel">
      <span className="muted small">{t("Saving makes version {n}; the monitors run it from their next cycle.", { n: algorithm.version + 1 })}</span>
      <div className="row-actions">
        <button type="button" className="button button-secondary" disabled={!changed} onClick={() => setDiagram(read.diagram)}>{t("Undo the changes")}</button>
        <button type="button" className="button button-primary" disabled={!changed} onClick={() => setSaving(true)}><Save size={16} />{t("Save as version {n}", { n: algorithm.version + 1 })}</button>
      </div>
    </div>}
    {saving && <VersionDialog next={algorithm.version + 1} who={me.name || me.username} busy={busy} error={error} onClose={() => setSaving(false)} onSave={(name, description) => void save(name, description)} />}
  </>;
}

/** The algorithm run once, nothing saved, laid out like a block's test (round 9): first where it
 * runs (an asset or a loop), then what each input reads there, then the window; its verdict and
 * every wire below. */
function TestTab({ read, specs, compare }: { read: Algorithm; specs: BlockSpecs; compare?: Array<{ label: string; algorithm: Algorithm }> }) {
  const [test, setTest] = useState<AlgorithmTest | null>(null);
  // Compare (D18): each version's test, all on the window the first one read.
  const [compared, setCompared] = useState<AlgorithmTest[] | null>(null);
  const [choices, setChoices] = useState<AssetChoice[]>([]);
  const [loops, setLoops] = useState<Array<{ loop_id: string; name: string }>>([]);
  const [subject, setSubject] = useState("");
  const [end, setEnd] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const onAssets = read.subject_kind === "asset";
  useEffect(() => {
    if (onAssets) assetChoices().then((found) => { setChoices(found); setSubject((now) => now || read.assets?.[0] || found[0]?.id || ""); }).catch(() => setChoices([]));
    else if (read.subject_kind === "loop") api.loops().then((items) => { setLoops(items); setSubject((now) => now || items[0]?.loop_id || ""); }).catch(() => setLoops([]));
  }, [read.algorithm_id, onAssets]);
  if (read.subject_kind === "signal") return <section className="panel"><p className="muted">{t("A signal algorithm is tested by its runs, on Signal quality.")}</p></section>;
  const own = new Set(read.assets ?? []);
  const options = onAssets
    ? [...choices].sort((a, b) => Number(own.has(b.id)) - Number(own.has(a.id)) || a.name.localeCompare(b.name)).map((item) => ({ id: item.id, name: item.path ? `${item.name} · ${item.path}` : item.name }))
    : loops.map((item) => ({ id: item.loop_id, name: item.name || item.loop_id }));
  const asset = choices.find((item) => item.id === subject);
  const reads = read.diagram.nodes.filter((node) => node.block.startsWith("input."));
  const role = (node: DiagramNode) => (node.parameters?.signal ? null : String(node.parameters?.role ?? ""));
  async function run() {
    setRunning(true); setError("");
    try {
      if (compare?.length) {
        const once = (item: Algorithm, window?: { start: string; end: string }) => (onAssets
          ? api.testOnAsset(item.diagram, subject, item.timing ?? DEFAULT_TIMING, window?.end ?? (end ? isoOf(end) : undefined))
          : api.testAlgorithm(item.diagram, subject, window));
        const first = await once(compare[0].algorithm);
        const span = first.summary?.window ?? (first.source_start && first.source_end ? { start: first.source_start, end: first.source_end } : undefined);
        setCompared([first, ...await Promise.all(compare.slice(1).map((item) => once(item.algorithm, span)))]);
      } else setTest(onAssets ? await api.testOnAsset(read.diagram, subject, read.timing ?? DEFAULT_TIMING, end ? isoOf(end) : undefined) : await api.testAlgorithm(read.diagram, subject));
    } catch (err) { setTest(null); setCompared(null); setError(err instanceof Error ? err.message : String(err)); } finally { setRunning(false); }
  }
  const verdict = test?.summary?.verdict;
  const blocked = read.check.valid ? "" : t("Fix the problems first.");
  return <section className="panel blkt" aria-label={t("Test")}>
    <div className="panel-header"><div>{compare
      ? <><h2>{t("Compare")}</h2><p>{t("Runs {versions} once each on the same data, without saving anything, and shows their outputs side by side.", { versions: compare.map((item) => item.label).join(", ") })}</p></>
      : <><h2>{t("Test")}</h2><p>{t("Runs this version once, without saving anything, and shows what every block said.")}</p></>}</div></div>
    <div className="blkt-step">
      <h3><span className="blkf-part-number pc-num" aria-hidden="true">1</span>{onAssets ? t("The asset") : t("The loop")}</h3>
      <select id="alg-test-subject" aria-label={onAssets ? t("Asset to test on") : t("Loop to test on")} value={subject} onChange={(event) => setSubject(event.target.value)}>
        {!subject && <option value="">{onAssets ? t("Choose an asset…") : t("Choose a loop…")}</option>}
        {options.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select>
    </div>
    {reads.length > 0 && <div className="blkt-step">
      <h3><span className="blkf-part-number pc-num" aria-hidden="true">2</span>{t("What each input reads")}</h3>
      <div className="blk-table-wrap"><table className="table blkt-points">
        <thead><tr><th>{t("Input")}</th><th>{t("Signal")}</th>{onAssets && <th>{t("On this asset")}</th>}</tr></thead>
        <tbody>{reads.map((node) => {
          const wanted = role(node);
          return <tr key={node.id}>
            <td><b>{nodeName(node, specs)}</b><small className="muted pc-mono"> {node.id}</small></td>
            <td>{wanted === null ? t("signal {id}", { id: String(node.parameters?.signal) }) : wanted || "—"}</td>
            {onAssets && <td>{wanted === null ? "—" : !asset ? "—" : asset.roles.includes(wanted) ? <Pill status="ok" label={t("found")} /> : <Pill status="warning" label={t("missing")} />}</td>}
          </tr>;
        })}</tbody>
      </table></div>
    </div>}
    {onAssets && <div className="blkt-step">
      <h3><span className="blkf-part-number pc-num" aria-hidden="true">{reads.length ? 3 : 2}</span>{t("The window")}</h3>
      <label className="alg-test-end">{t("Ending at (empty: now)")}<input type="datetime-local" value={end} onChange={(event) => setEnd(event.target.value)} /></label>
    </div>}
    <div className="row-actions blkt-run">
      <button type="button" className="button button-primary" title={blocked || undefined} disabled={!!blocked || running || !subject} onClick={() => void run()}><FlaskConical size={16} />{running ? t("Running…") : compare ? t("Run and compare") : t("Run the test")}</button>
      {error && <span className="alg-test-error" role="alert">{error}</span>}
    </div>
    {compared && compare && <CompareView columns={compare.map((item) => item.label)} subject={compared[0].asset_name ?? compared[0].loop_id ?? subject}
      window={compared[0].summary?.window ?? (compared[0].source_start && compared[0].source_end ? { start: compared[0].source_start, end: compared[0].source_end } : null)}
      comparison={algorithmComparison(compare.map((item, index) => ({ diagram: item.algorithm.diagram, trace: compared[index]?.trace, outputs: (compared[index]?.summary as { outputs?: AlgorithmOutput[] } | undefined)?.outputs })))} />}
    {test && <p className="alg-test-verdict">
      {verdict
        ? <><Pill status={verdict.status === "bad" ? "alarm" : verdict.status} label={resultLabel(verdict.status)} /> {verdict.message}</>
        : test.summary && <><Pill status={test.summary.status ?? "unknown"} label={test.summary.health !== null && test.summary.health !== undefined ? t("Health {value} %", { value: Math.round(test.summary.health) }) : t("Ran")} /></>}
    </p>}
    {test?.trace && <AlgorithmDiagram algorithmId={read.algorithm_id} algorithm={read} trace={test.trace} height={520} />}
  </section>;
}

/** The Compare tab (D18): the versions of `?versions=`, each read as saved, run on the same data. */
function AlgorithmCompare({ algorithm, specs }: { algorithm: Algorithm; specs: BlockSpecs }) {
  const numbers = comparedVersions(window.location.search).filter((number) => number <= algorithm.version);
  const [versions, setVersions] = useState<Algorithm[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (numbers.length < 2) return;
    Promise.all(numbers.map((number) => api.algorithmVersion(algorithm.algorithm_id, number))).then(setVersions).catch((err: Error) => setError(err.message));
  }, [algorithm.algorithm_id, numbers.join(",")]);
  if (numbers.length < 2) return <section className="panel"><p className="muted">{t("Tick two or three versions on the Versions tab to compare them.")}</p></section>;
  if (error) return <ErrorBox text={error} />;
  if (!versions) return <Loading />;
  return <TestTab read={versions[versions.length - 1]} specs={specs} compare={versions.map((item, index) => ({ label: t("Version {number}", { number: numbers[index] }), algorithm: item }))} />;
}

/** The name of a new version and what changed in it, with who saves it (D16, D19). */
function VersionDialog({ next, who, busy, error, onClose, onSave }: { next: number; who: string; busy: boolean; error: string; onClose: () => void; onSave: (name: string, description: string) => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const title = t("Save as version {n}", { n: next });
  return <Dialog title={title} onClose={onClose} onSubmit={(event) => { event.preventDefault(); onSave(name.trim(), description.trim()); }}>
    <div className="form-grid">
      <label>{t("Version name")}<input id="alg-version-name" value={name} required maxLength={120} onChange={(event) => setName(event.target.value)} placeholder={t("Wider window")} /></label>
      <label className="blkf-wide">{t("What changed")}<textarea id="alg-version-note" rows={3} value={description} required maxLength={2000} onChange={(event) => setDescription(event.target.value)} /></label>
    </div>
    <p className="muted small">{t("Saved by {name}, with the date: the version's history shows who made each change.", { name: who })}</p>
    {error && <div className="notice notice-error" role="alert">{error}</div>}
    <footer><button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button><button className="button button-primary" disabled={busy || !name.trim() || !description.trim()}><Save size={16} />{busy ? t("Saving…") : title}</button></footer>
  </Dialog>;
}

/**
 * `/algorithms/<id>/edit[?version=N]`: New version (owner D19, 2026-10-26). One form, filled in
 * from the version shown: what it is, its diagram (edited and tested here), the data each run
 * reads and every block's parameters; saving makes the next version with its own name.
 */
function NewVersion({ algorithm, from, specs, me, onSaved: saved }: { algorithm: Algorithm; from: Algorithm; specs: BlockSpecs; me: Me; onSaved: (next: Algorithm) => void }) {
  const start = () => ({ name: from.name, description: from.description, docs: { ...EMPTY_DOCS, ...from.docs }, diagram: from.diagram, timing: from.timing ?? DEFAULT_TIMING });
  const [draft, setDraft] = useState(start);
  const [catalog, setCatalog] = useState<BlockCatalog | null>(null);
  const [check, setCheck] = useState<DiagramCheck | null>(from.check);
  const [test, setTest] = useState<AlgorithmTest | null>(null);
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { setDraft(start()); }, [from]);
  useEffect(() => { blockCatalog().then((found) => setCatalog(found as unknown as BlockCatalog)).catch((err: Error) => setError(err.message)); }, []);
  useEffect(() => {
    const timer = window.setTimeout(() => { api.checkAlgorithm(draft.diagram).then(setCheck).catch(() => undefined); }, 300);
    return () => window.clearTimeout(timer);
  }, [draft.diagram]);
  const base = `/algorithms/${encodeURIComponent(algorithm.algorithm_id)}`;
  const changed = JSON.stringify(draft) !== JSON.stringify(start());
  useEffect(() => {
    if (!changed) return undefined;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [changed]);
  const next = algorithm.version + 1;
  const nodes = withParameters(draft.diagram, specs);
  const setDiagram = (diagram: Diagram) => { setDraft((now) => ({ ...now, diagram })); setTest(null); };
  const blocked = check && !check.valid ? t("Fix the problems first.") : "";
  async function save(name: string, description: string) {
    setBusy(true); setError("");
    try { saved(await saveChanged(algorithm, draft, { name, description })); navigate(base); } catch (err) { setError(err instanceof Error ? err.message : String(err)); } finally { setBusy(false); }
  }
  let part = 0;
  const head = (title: string, detail?: string, aside?: ReactNode) => <header className="blkf-part-head"><span className="blkf-part-number pc-num" aria-hidden="true">{++part}</span><div><h2>{title}</h2>{detail && <p>{detail}</p>}</div>{aside}</header>;
  return <div className="blkf">
    <section className="panel blkf-part" id="alg-edit-about">
      {head(t("What it is"), t("People and the suite's assistant read this. A field left empty shows the text the diagram gives (in grey)."))}
      <div className="form-grid">
        <label className="blkf-wide">{t("Name")}<input id="alg-name" value={draft.name} maxLength={120} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label>
        <label className="blkf-wide">{t("Description")}<textarea id="alg-description" rows={2} value={draft.description} maxLength={2000} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></label>
      </div>
      <details className="blkf-details">
        <summary>{t("Purpose, assets, when to use it, how to read it, for the assistant")}</summary>
        <div className="form-grid">{DOC_FIELDS.map((field) => <label key={field} className="blkf-wide">{t(DOC_TITLES[field])}
          <textarea id={`alg-doc-${field}`} rows={field === "purpose" ? 2 : 3} value={draft.docs[field]} placeholder={algorithm.docs_generated[field]} maxLength={field === "purpose" ? 400 : 4000}
            onChange={(event) => setDraft({ ...draft, docs: { ...draft.docs, [field]: event.target.value } })} />
          <small>{t(DOC_HELP[field])}</small>
        </label>)}</div>
      </details>
    </section>
    <section className="panel blkf-part" id="alg-edit-diagram">
      {head(t("The diagram"), t("Drag blocks from the palette and wire an output to an input of the same type. Test runs it once, nothing saved, and shows what every wire carried."),
        algorithm.subject_kind === "signal" ? undefined : <span className="alg-edit-test">{algorithm.subject_kind === "asset"
          ? <AssetTestControl diagram={draft.diagram} draft={{ assets: algorithm.assets ?? [], timing: draft.timing }} onTrace={setTest} disabled={blocked} />
          : <TestControl diagram={draft.diagram} onTrace={setTest} disabled={blocked} />}</span>)}
      {catalog
        ? <div className="alg-diagram alg-edit-diagram"><BlockEditor catalog={catalog} diagram={draft.diagram} onChange={setDiagram} check={check} trace={test?.trace ?? null} blockHref={(blockId) => href(`/blocks/${encodeURIComponent(blockId)}`)}
          inspectorTools={(node) => node.block === DEVIATION_BLOCK && algorithm.subject_kind === "asset"
            ? <CalibrateTool node={node} diagram={draft.diagram} timing={draft.timing} assets={algorithm.assets ?? []} readOnly={false} disabled={blocked} onCalibrated={setDiagram} />
            : null} /></div>
        : <Loading />}
    </section>
    {algorithm.subject_kind === "asset" && <section className="panel blkf-part" id="alg-edit-window">
      {head(t("The data each run reads"))}
      <TimingFields timing={draft.timing} onChange={(timing) => setDraft({ ...draft, timing })} />
    </section>}
    <section className="panel blkf-part" id="alg-edit-parameters">
      {head(t("Parameters"), t("Each block's settings. A value left as it is follows the block's default."))}
      {!nodes.length && <p className="muted">{t("No block of this algorithm has parameters.")}</p>}
      {nodes.map((node) => <div key={node.id} className="blkf-row alg-node-parameters">
        <h3>{nodeName(node, specs)} <small className="muted"><Link to={`/blocks/${encodeURIComponent(node.block)}`}>{specs[node.block]?.name ?? node.block}</Link> · <span className="pc-mono">{node.id}</span></small></h3>
        <div className="alg-node-fields">{specs[node.block].parameters.map((parameter) => <ParameterField key={parameter.name} node={node} parameter={parameter} readOnly={false}
          onSet={(value) => setDraft((now) => ({ ...now, diagram: setParameter(now.diagram, node.id, parameter.name, value) }))} />)}</div>
      </div>)}
    </section>
    {check && !check.valid && <div className="notice notice-error">{check.errors.join(" ")}</div>}
    <div className="blkf-bar panel">
      <span className="muted small">{t("Filled in from version {number}. Saving makes version {n}; the monitors run it from their next cycle.", { number: from.version, n: next })}</span>
      <div className="row-actions">
        <button type="button" className="button button-secondary" onClick={() => navigate(from.version === algorithm.version ? base : `${base}?version=${from.version}`)}>{t("Cancel")}</button>
        <button type="button" className="button button-primary" title={blocked || undefined} disabled={!changed || !!blocked || !draft.name.trim()} onClick={() => setSaving(true)}><Save size={16} />{t("Save as version {n}", { n: next })}</button>
      </div>
    </div>
    {saving && <VersionDialog next={next} who={me.name || me.username} busy={busy} error={error} onClose={() => setSaving(false)} onSave={(name, description) => void save(name, description)} />}
  </div>;
}

/** Shown above the tabs while the page shows an older version (D17, D19): back to the one in use,
 * or Use this version, which saves it again as the newest. */
function ShownVersion({ algorithm, read, editable, onUsed }: { algorithm: Algorithm; read: Algorithm; editable: boolean; onUsed: (next: Algorithm) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const base = `/algorithms/${encodeURIComponent(algorithm.algorithm_id)}`;
  async function use() {
    setBusy(true); setError("");
    try {
      const { name, description, docs, diagram, timing, assets } = read;
      onUsed(await saveChanged(algorithm, { name, description, docs, diagram, timing, assets }, { name: t("Back to version {number}", { number: read.version }), description: "" }));
      navigate(base);
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); } finally { setBusy(false); }
  }
  return <div className="notice blk-shown" role="status">
    <div>
      <b>{t("Showing version {number} of {name}", { number: read.version, name: algorithm.name })}</b>
      <p className="small">{t("Version {number} is the one in use: the monitors run it.", { number: algorithm.version })}</p>
      {error && <p className="small" role="alert">{error}</p>}
    </div>
    <div className="row-actions">
      <Link to={base} className="button button-secondary button-small">{t("Back to version {number}", { number: algorithm.version })}</Link>
      {editable && <button type="button" className="button button-primary button-small" disabled={busy} title={t("Saves this version again as version {n}.", { n: algorithm.version + 1 })} onClick={() => void use()}>{t("Use this version")}</button>}
    </div>
  </div>;
}

/** Where it is used: its assets (an algorithm on assets) or its loops, and its schedules. */
function UsedByTab({ algorithm, me, onSaved }: { algorithm: Algorithm; me: Me; onSaved: (next: Algorithm) => void }) {
  const id = algorithm.algorithm_id;
  const [assets, setAssets] = useState(algorithm.assets ?? []);
  const [types, setTypes] = useState(algorithm.asset_types ?? []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { setAssets(algorithm.assets ?? []); setTypes(algorithm.asset_types ?? []); }, [algorithm]);
  const changed = JSON.stringify(assets) !== JSON.stringify(algorithm.assets ?? []) || JSON.stringify(types) !== JSON.stringify(algorithm.asset_types ?? []);
  async function save() {
    setBusy(true); setError("");
    try { onSaved(await saveChanged(algorithm, { assets, asset_types: types })); } catch (err) { setError(err instanceof Error ? err.message : String(err)); } finally { setBusy(false); }
  }
  if (algorithm.subject_kind === "signal" && id === SIGNAL_QUALITY) return <div className="panel used-by"><p>{t("Every active signal PlantCraft knows. The loop algorithms read its results before they judge a loop.")}</p><div className="row-actions"><Link to="/algorithms/signal_quality/settings" className="button button-secondary">{t("Monitor and checks")}</Link></div></div>;
  if (algorithm.subject_kind !== "asset") return <><Usage algorithmId={id} /><Schedules algorithmId={id} /></>;
  return <>
    <AssetRuns algorithmId={id} assets={algorithm.assets ?? []} types={algorithm.asset_types ?? []} me={me} />
    {algorithm.editable && <section className="panel alg-docs"><div className="panel-header"><div><h2>{t("Its assets")}</h2><p>{t("The assets Run now and the monitors that follow the algorithm run it on.")}</p></div></div>
      <AssetPicker assets={assets} onChange={setAssets} />
      <h3>{t("And every asset of a type")}</h3>
      <p className="muted small">{t("The algorithm also runs on every asset of these PlantCraft types, subtypes included: one algorithm for every pump, every exchanger. An asset of the type added later is included at the next run of a monitor on every asset of the algorithm.")}</p>
      <AssetTypePicker types={types} onChange={setTypes} />
      {error && <div className="notice notice-error" role="alert">{error}</div>}
      <div className="row-actions"><button type="button" className="button button-primary" disabled={!changed || busy} onClick={() => void save()}><Save size={16} />{busy ? t("Saving…") : t("Save as new version")}</button></div>
    </section>}
    <Schedules algorithmId={id} />
  </>;
}

/**
 * `/algorithms/<id>[/inputs|diagram|test|used-by|versions|edit][?version=N]`: one algorithm, with
 * the same tabs as a block (owner D19, 2026-10-26: Overview, Inputs and outputs, Diagram, Test,
 * Used by, Versions) and, like a block, New version for its next one, at the version in use or the
 * one asked for.
 */
export function AlgorithmPage({ algorithmId, tab, me }: { algorithmId: string; tab: AlgorithmTab; me: Me }) {
  const [algorithm, setAlgorithm] = useState<Algorithm | null>(null);
  const [specs, setSpecs] = useState<BlockSpecs>({});
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);
  const [shown, setShown] = useState<Algorithm | null>(null);
  const asked = Number(new URLSearchParams(window.location.search).get("version")) || 0;
  const load = () => api.algorithm(algorithmId).then((found) => { setAlgorithm(found); setError(""); }).catch((err: Error) => setError(err.message));
  useEffect(() => {
    void load();
    blockCatalog().then((catalog) => setSpecs(Object.fromEntries(catalog.blocks.map((block) => [block.block_id, block])))).catch(() => setSpecs({}));
    return onSaved((id) => { if (id === algorithmId) { void load(); setVersion((now) => now + 1); } });
  }, [algorithmId]);
  useEffect(() => {
    if (!asked || !algorithm || asked === algorithm.version) { setShown(null); return; }
    api.algorithmVersion(algorithmId, asked).then(setShown).catch((err: Error) => setError(err.message));
  }, [algorithmId, asked, algorithm?.version]);
  if (error) return <ErrorBox text={error} />;
  if (!algorithm) return <Loading />;
  const id = algorithm.algorithm_id;
  const read = shown && asked && shown.version === asked && shown.version !== algorithm.version ? shown : algorithm;
  const older = read !== algorithm;
  const editable = Boolean(algorithm.editable) && !algorithm.system && me.can_edit;
  const base = `/algorithms/${encodeURIComponent(id)}`;
  // The tabs keep the version shown.
  const at = older ? `?version=${read.version}` : "";
  function show(number: number) {
    navigate(number === algorithm!.version ? base : `${base}?version=${number}`);
  }
  const saved = (next: Algorithm) => { setAlgorithm(next); setShown(null); setVersion((now) => now + 1); };
  async function remove() {
    if (!(await confirmAction(t("Delete {name}? This cannot be undone.", { name: algorithm!.name }), { confirm: t("Delete"), danger: true }))) return;
    try { await api.deleteAlgorithm(id); navigate("/algorithms"); } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }
  if (tab === "edit" && editable) return <>
    <nav className="breadcrumb"><Link to="/algorithms">{t("Algorithms")}</Link><ChevronRight size={12} /><Link to={base}>{algorithm.name}</Link><ChevronRight size={12} /><span>{t("New version")}</span></nav>
    <Heading title={t("New version of {name}", { name: algorithm.name })} />
    {asked && asked !== algorithm.version && !shown ? <Loading /> : <NewVersion algorithm={algorithm} from={read} specs={specs} me={me} onSaved={saved} />}
  </>;
  return <>
    <nav className="breadcrumb"><Link to="/algorithms">{t("Algorithms")}</Link><ChevronRight size={12} /><span>{algorithm.name}</span></nav>
    <Heading eyebrow={`${algorithm.system ? t("PlantCraft's algorithm") : t("Site algorithm")} · ${t(KIND_LABEL[algorithm.subject_kind])} · ${t("version {number}", { number: algorithm.version })}`}
      title={algorithm.name} detail={algorithm.description || undefined}
      actions={<>
        <LinkAssistant kind="algorithm" id={id} me={me} title={algorithm.name} />
        {me.can_edit && <button className="button button-secondary" onClick={() => openEditor(null, id)}><Copy size={16} />{t("Duplicate")}</button>}
        <button className="button button-secondary" onClick={() => downloadAlgorithmFile(read)}><Download size={16} />{t("Download the file")}</button>
        {algorithm.editable && <button className="button button-secondary" onClick={() => void remove()}><Trash2 size={16} />{t("Delete")}</button>}
      </>} />
    <FolderPlaceLine kind="algorithm" itemId={algorithm.algorithm_id} canEdit={me.can_edit} />
    {older && <ShownVersion algorithm={algorithm} read={read} editable={editable} onUsed={saved} />}
    <PageTabs label={t("Algorithm")} href={href} navigate={navigate} tabs={[
      { to: `${base}${at}`, label: t("Overview"), active: tab === "overview" || tab === "edit" },
      { to: `${base}/inputs${at}`, label: t("Inputs and outputs"), active: tab === "inputs" },
      { to: `${base}/diagram${at}`, label: t("Diagram"), active: tab === "diagram" },
      { to: `${base}/test${at}`, label: t("Test"), active: tab === "test" },
      { to: `${base}/used-by${at}`, label: t("Used by"), active: tab === "used-by" },
      { to: `${base}/versions${at}`, label: t("Versions"), active: tab === "versions" },
      { to: `${base}/settings${at}`, label: t("Settings"), active: tab === "settings" },
      ...(tab === "compare" ? [{ to: `${base}/compare${window.location.search}`, label: t("Compare"), active: true }] : []),
    ]} />
    <div className="blk-tab">
      {!read.check.valid && <div className="notice notice-error">{read.check.errors.join(" ")}</div>}
      {(tab === "overview" || tab === "edit") && <Texts read={read} />}
      {tab === "diagram" && <section className="panel alg-page-diagram">
        <AlgorithmDiagram key={`${version}-${read.version}`} algorithmId={id} algorithm={older ? read : undefined} height={600} />
      </section>}
      {tab === "inputs" && <InputsTab key={`${read.algorithm_id}-${read.version}`} algorithm={algorithm} read={read} specs={specs} me={me} editable={editable && !older} newVersion={editable ? `${base}/edit${at}` : null} onSaved={saved} />}
      {tab === "settings" && <div className="alg-settings">
        {/* Who answers for it and where its runs go: settings, not versions. */}
        <Stewardship key={`${algorithm.algorithm_id}-${algorithm.version}`} algorithm={algorithm} me={me} onSaved={saved} />
        <WhereItRuns key={`where-${algorithm.algorithm_id}-${algorithm.version}`} algorithm={algorithm} onSaved={saved} />
      </div>}
      {tab === "test" && <TestTab read={read} specs={specs} />}
      {tab === "used-by" && <UsedByTab algorithm={algorithm} me={me} onSaved={saved} />}
      {tab === "versions" && <VersionsOfAlgorithm algorithm={algorithm} me={me} shown={read.version} newVersion={editable ? `${base}/edit${at}` : null} onShow={show} onSaved={setAlgorithm} />}
      {tab === "versions" && <ComparePicker numbers={Array.from({ length: algorithm.version }, (_, index) => index + 1)} base={base} />}
      {tab === "compare" && <AlgorithmCompare algorithm={algorithm} specs={specs} />}
    </div>
  </>;
}

const DOC_TITLES: Record<(typeof DOC_FIELDS)[number], string> = {
  purpose: "Purpose",
  assets: "Assets",
  when: "When to use it",
  reading: "How to read it",
  assistant: "For the assistant",
};

const DOC_HELP: Record<(typeof DOC_FIELDS)[number], string> = {
  purpose: "The question it answers, in one sentence.",
  assets: "Which loops or signals it fits, and what they need (signals, modes).",
  when: "When to choose it over another algorithm, and when not.",
  reading: "What its result means and what a bad one asks people to check.",
  assistant: "How a specialist should explain its results: what to check first, what not to claim.",
};
