/**
 * Blocks: every block an algorithm can use, by library (round 10: libraries, no folders; a site
 * makes its own with New library), with who made it and its version. A block's page has the same
 * tabs as an algorithm's (its docs, its inputs and outputs, its one calculation, a test on an
 * asset, the algorithms that use it, its versions: owner D15, 2026-10-26). Duplicate, beside
 * Download the file, makes a new block from it; New version, on the Versions tab, the next
 * version of a site block. A block PlantCraft ships shows a lock there: it gets no new version
 * on the site (round 10), Duplicate makes one's own. Any version opens on the page
 * (`?version=N`) and Select version sets the one in use (D17).
 */
import { BlockDrawing, CodeDiff, comparedVersions, confirmAction, LibraryColumn, lineDiff, PageTabs, useAssistantPage, VersionLock, VersionsTab, type VersionItem } from "@plantcraft/ui";
import { typeLabel, type PortSpec } from "@plantcraft/ui/blockEditor";
import "@plantcraft/ui/codeEditor.css";
import { CodeEditor } from "@plantcraft/ui/codeEditor";
import { ChevronRight, Copy, Download, Lock, PenLine, Plus, Search, SlidersHorizontal, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { linkRef } from "./Assistant";
import { blockCatalog, forgetBlockCatalog } from "./blockCatalog";
import { openEditor } from "./algorithms";
import { canWriteBlocks, EditBlockPage } from "./BlockEdit";
import { ComparePicker } from "./Compare";
import { downloadBlockFile } from "./blockFile";
import { BlockTest } from "./BlockTest";
import { formatDate, t } from "./i18n";
import { href, navigate } from "./nav";
import type { BlockCode, BlockDetail, Blocks, CatalogBlock, Me, MethodSpec, ModelRow } from "./types";
import { NewLibraryButton } from "./NewLibrary";
import { ErrorBox, Heading, Link, Loading } from "./ui";

/** The library a Blocks page opens on: ?library= in the address, else the first. */
export function chosenLibrary(libraries: Array<{ library: string }>, search: string): string {
  const asked = new URLSearchParams(search).get("library");
  return libraries.find((item) => item.library === asked)?.library ?? libraries[0]?.library ?? "";
}

export const BLOCK_TABS = ["inputs", "code", "test", "used-by", "versions"] as const;
export type BlockTab = "overview" | (typeof BLOCK_TABS)[number] | "edit" | "compare";

/** Tabs a block page had before round 8, for the links people kept. */
const OLD_TABS: Record<string, BlockTab> = { parameters: "inputs" };

/** `/blocks/<id>/<tab>` -> the block id and the tab (block ids contain dots, never slashes). */
export function blockRoute(id: string): { blockId: string; tab: BlockTab } {
  const [blockId, tab] = id.split("/");
  if (tab === "edit") return { blockId, tab: "edit" };
  if (tab === "compare") return { blockId, tab: "compare" };
  if (tab && tab in OLD_TABS) return { blockId, tab: OLD_TABS[tab] };
  return { blockId, tab: (BLOCK_TABS as readonly string[]).includes(tab ?? "") ? (tab as BlockTab) : "overview" };
}

/** Who made a block, as its card and page say it. */
export function madeBy(block: Pick<CatalogBlock, "site" | "author_name" | "number">): string {
  return block.site ? t("{name} · version {number}", { name: block.author_name, number: block.number ?? "?" }) : t("PlantCraft");
}

function Ports({ ports }: { ports: PortSpec[] }) {
  if (!ports.length) return <span className="muted">—</span>;
  return <span className="blk-ports">{ports.map((port) => <span key={port.port} className={`blk-port blk-type-${port.type}`} title={port.description}>{port.label}<small>{typeLabel(port.type)}</small></span>)}</span>;
}

const pageId = (block: CatalogBlock) => (block.site ? block.family : block.block_id);

export function BlocksPage({ me }: { me: Me }) {
  const [catalog, setCatalog] = useState<Blocks | null>(null);
  const [current, setCurrent] = useState("");
  const [query, setQuery] = useState("");
  const [maker, setMaker] = useState<"all" | "site" | "plantcraft">("all");
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(0);
  useEffect(() => { blockCatalog().then((found) => { setCatalog(found); setCurrent((now) => chosenLibrary(found.libraries, now ? `?library=${encodeURIComponent(now)}` : window.location.search)); }).catch((err: Error) => setError(err.message)); }, [loaded]);
  useAssistantPage({ place: t("Analytics › Blocks"), page: "linkcraft:blocks", platformUrl: me.processcraft_url, view: { library: current, search: query, made_by: maker } });
  const words = query.trim().toLowerCase();
  const matches = useMemo(() => (block: CatalogBlock) => {
    if (maker === "site" && !block.site) return false;
    if (maker === "plantcraft" && block.site) return false;
    if (!words) return true;
    return `${block.name} ${block.block_id} ${block.summary} ${block.author_name} ${(block.tags ?? []).join(" ")} ${block.group ?? ""}`.toLowerCase().includes(words);
  }, [maker, words]);
  if (error) return <ErrorBox text={error} />;
  if (!catalog) return <Loading />;
  const choose = (library: string) => { setQuery(""); setMaker("all"); setCurrent(library); window.history.replaceState({}, "", href(`/blocks?library=${encodeURIComponent(library)}`)); };
  const library = catalog.libraries.find((item) => item.library === current) ?? catalog.libraries[0];
  const searching = Boolean(words) || maker !== "all";
  const shown = searching ? catalog.blocks.filter(matches) : library ? catalog.blocks.filter((item) => item.library === library.library) : [];
  // New block starts in the library shown when a site block may join it.
  const into = library && (catalog.open_libraries ?? []).includes(library.library) ? `?library=${encodeURIComponent(library.library)}` : "";
  return <>
    <Heading eyebrow={t("Algorithms and blocks")} title={t("Blocks")} detail={t("Every block an algorithm can use, by library, with its typed inputs and outputs, its parameters, its code and who made it. The editor's palette and the assistant read the same descriptions.")}
      actions={me.can_edit && <Link to={`/blocks/new${into}`} className="button button-primary"><Plus size={16} />{t("New block")}</Link>} />
    <div className="blk-filters">
      <label className="blk-search"><Search size={15} /><input id="blk-search" type="search" value={query} placeholder={t("Search blocks, labels, authors…")} aria-label={t("Search blocks")} onChange={(event) => setQuery(event.target.value)} /></label>
      <div className="segmented" role="group" aria-label={t("Made by")}>
        {([["all", t("All")], ["plantcraft", t("PlantCraft")], ["site", t("This site")]] as const).map(([value, label]) => <button key={value} type="button" className={maker === value ? "active" : ""} aria-pressed={maker === value} onClick={() => setMaker(value)}>{label}</button>)}
      </div>
    </div>
    <div className="pc-folder-layout">
      <LibraryColumn libraries={catalog.libraries.map((item) => ({ ...item, count: catalog.blocks.filter((block) => block.library === item.library).length }))}
        chosen={searching ? "" : library?.library ?? ""} onChoose={choose}
        footer={canWriteBlocks(me) && <NewLibraryButton onMade={(made) => { setCurrent(made.library); window.history.replaceState({}, "", href(`/blocks?library=${encodeURIComponent(made.library)}`)); setLoaded((now) => now + 1); }} />} />
      <section className="methods-main">
        {searching
          ? <div className="pc-folder-head"><h2>{t("{count} blocks found", { count: shown.length })}</h2></div>
          : library && <div className="pc-folder-head"><h2>{library.name}</h2><p className="muted">{library.description}</p></div>}
        {shown.length
          ? <div className="pc-grid">{shown.map((item) => <Link key={item.block_id} to={`/blocks/${encodeURIComponent(pageId(item))}`} className="panel card blk-card">
            <span className="eyebrow pc-mono">{pageId(item)}</span><strong>{item.name}</strong><p>{item.summary}</p>
            <small className="blk-card-ports">{item.inputs.length > 0 && <span><b>{t("In")}</b><Ports ports={item.inputs} /></span>}<span><b>{t("Out")}</b><Ports ports={item.outputs} /></span></small>
            <small className="blk-card-by">{!item.site && <Lock size={12} aria-label={t("Ships with PlantCraft")} />}{madeBy(item)}{(item.tags ?? []).map((tag) => <span key={tag} className="tag">{tag}</span>)}</small>
          </Link>)}</div>
          : <div className="panel empty"><p>{searching ? t("No block matches.") : into ? t("No block in this library yet. New block imports a block file, opens the form or asks an assistant to write one.") : t("No block matches.")}</p></div>}
      </section>
    </div>
  </>;
}

const portRow = (port: PortSpec) => <tr key={`port-${port.port}`}>
  <td><b>{port.label}</b><small className="pc-mono">{port.port}</small></td>
  <td><span className={`blk-port blk-type-${port.type}`}>{port.types.map(typeLabel).join(" / ")}</span></td>
  <td>{port.unit || <span className="muted">—</span>}</td>
  <td>{port.description}{(port.required || port.multiple || port.record) && <small>{[port.required ? t("required") : "", port.multiple ? t("takes several wires") : "", port.record ? t("recorded in the historian by default") : ""].filter(Boolean).join(" · ")}</small>}</td>
</tr>;

/** Inputs, outputs and parameters in one table, so their columns line up. */
function ContractTable({ block, parameters = true }: { block: BlockDetail; parameters?: boolean }) {
  const groups: Array<[string, React.ReactNode[]]> = [
    [t("Inputs"), block.inputs.map(portRow)],
    [t("Outputs"), block.outputs.map(portRow)],
  ];
  if (parameters) groups.push([t("Parameters"), block.parameters.map((item) => <tr key={`parameter-${item.name}`}>
    <td><b>{item.title}</b><small className="pc-mono">{item.name}</small></td>
    <td><span className="blk-port">{t("parameter")}</span></td>
    <td className="pc-mono">{JSON.stringify(item.default)}{item.unit && ` ${item.unit}`}</td>
    <td>{item.description}</td>
  </tr>)]);
  const shown = groups.filter(([, rows]) => rows.length);
  if (!shown.length) return <p className="muted">{t("No inputs, outputs or parameters.")}</p>;
  return <div className="blk-table-wrap"><table className="table blk-contract">
    <colgroup><col className="blk-col-name" /><col className="blk-col-type" /><col className="blk-col-value" /><col /></colgroup>
    <thead><tr><th>{t("Name")}</th><th>{t("Type")}</th><th>{t("Unit or default")}</th><th>{t("Description")}</th></tr></thead>
    {shown.map(([title, rows]) => <tbody key={title}><tr className="blk-group"><th colSpan={4} scope="colgroup">{title}</th></tr>{rows}</tbody>)}
  </table></div>;
}

/** Who answers for a site block and its tags (not part of a version). */
function Stewardship({ block, me, onSaved }: { block: BlockDetail; me: Me; onSaved: () => void }) {
  const [people, setPeople] = useState<Array<{ username: string; name: string }>>([]);
  const [owner, setOwner] = useState(block.owner);
  const [tags, setTags] = useState((block.tags ?? []).join(", "));
  const [note, setNote] = useState("");
  const editable = block.site && canWriteBlocks(me);
  useEffect(() => { if (editable) api.blockPeople().then(setPeople).catch(() => setPeople([])); }, [editable]);
  async function save() {
    try {
      const person = people.find((item) => item.username === owner);
      await api.updateBlock(block.family, { owner, owner_name: person?.name ?? owner, tags: tags.split(",").map((item) => item.trim()).filter(Boolean) });
      forgetBlockCatalog();
      setNote(t("Saved."));
      onSaved();
    } catch (err) { setNote(err instanceof Error ? err.message : String(err)); }
  }
  return <section className="panel blk-who">
    <div className="panel-header"><div><h2>{t("About it")}</h2></div></div>
    <dl>
      <dt>{t("Made by")}</dt><dd>{block.author_name}</dd>
      <dt>{t("Answers for it")}</dt><dd>{editable
        ? <select id="blk-owner" value={owner} onChange={(event) => setOwner(event.target.value)}>
          {!people.some((item) => item.username === owner) && <option value={owner}>{block.owner_name || owner}</option>}
          {people.map((item) => <option key={item.username} value={item.username}>{item.name}</option>)}
        </select>
        : block.owner_name}</dd>
      <dt>{t("Origin")}</dt><dd>{t(ORIGINS[block.origin] ?? block.origin)}</dd>
      <dt>{t("Labels")}</dt><dd>{editable
        ? <input id="blk-tags" value={tags} onChange={(event) => setTags(event.target.value)} placeholder={t("fouling, heat exchanger")} />
        : (block.tags ?? []).length ? block.tags.map((tag) => <span key={tag} className="tag">{tag}</span>) : <span className="muted">—</span>}</dd>
    </dl>
    {editable && <div className="row-actions"><button type="button" className="button button-secondary button-small" onClick={() => void save()}>{t("Save owner and labels")}</button>{note && <small className="muted">{note}</small>}</div>}
  </section>;
}

const ORIGINS: Record<string, string> = {
  user: "Written on this site",
  assistant: "Written with an assistant",
  import: "Imported from a file",
  plantcraft: "Ships with Analytics",
  "modelcraft-fmu": "A model published from Models",
};

/** A block's versions, newest first, in their own tab: a block Link ships is version 1, and the
 * site's edits of it are 2, 3…. "current" is the one in use; opening one
 * shows the block's page at that version. */
export function blockVersions(block: Pick<BlockDetail, "site" | "versions" | "number" | "version" | "in_use">): VersionItem[] {
  if (!block.site) return [{ number: 1, name: t("Analytics' version"), author: t("PlantCraft"), note: t("ships with Analytics {version}", { version: block.version }), current: true }];
  return (block.versions ?? []).map((item) => ({
    number: item.number, name: item.name, description: item.description, author: item.author_name, at: item.created_at,
    note: item.shipped ? t("ships with Analytics {version}", { version: block.version }) : null, current: item.number === (block.in_use ?? block.number),
  }));
}

/** The id a version runs by: Link's shipped version 1 is the block's own id, the others pinned. */
export function versionBlockId(block: Pick<BlockDetail, "family" | "versions">, number: number): string {
  return (block.versions ?? []).find((item) => item.number === number)?.shipped ? block.family : `${block.family}.v${number}`;
}

/** The Compare tab (D18): the versions of `?versions=` run on the same asset and window. */
function BlockCompare({ block }: { block: BlockDetail }) {
  const numbers = comparedVersions(window.location.search).filter((number) => (block.versions ?? []).some((item) => item.number === number));
  if (numbers.length < 2) return <section className="panel"><p className="muted">{t("Tick two or three versions on the Versions tab to compare them.")}</p></section>;
  return <BlockTest key={numbers.join(",")} subject={{ block_id: block.block_id }} inputs={block.inputs} outputs={block.outputs}
    compare={numbers.map((number) => ({ label: t("Version {number}", { number }), block_id: versionBlockId(block, number) }))} />;
}

/** Whether New version is offered: a site block (one PlantCraft ships is locked, round 10; the
 * server refuses its new versions too, even where the site saved some before). */
export function canNewVersion(block: Pick<BlockDetail, "site" | "editable" | "locked">, writer: boolean): boolean {
  return Boolean(block.site && block.editable && !block.locked) && writer;
}

function BlockVersions({ block, base, me, newVersion, onSaved }: { block: BlockDetail; base: string; me: Me; newVersion: string | null; onSaved: () => void }) {
  return <VersionsTab
    about={<Stewardship block={block} me={me} onSaved={onSaved} />}
    versions={blockVersions(block)}
    shown={block.site ? block.number ?? undefined : 1}
    onOpen={(number) => navigate(versionAddress(base, number, block))}
    actions={newVersion ? <Link to={newVersion} className="button button-primary"><PenLine size={16} />{t("New version")}</Link>
      : !block.site || block.locked ? <VersionLock>{t("Ships with PlantCraft: no new version here")}</VersionLock> : null}
    footer={!block.site || block.locked ? t("A block PlantCraft ships changes with PlantCraft itself. Duplicate it to make a block of this site from it.") : t("Algorithms keep the version they name until someone updates them.")} />;
}

function UsedBy({ block }: { block: BlockDetail }) {
  if (!block.used_by.length) return <section className="panel"><p className="muted">{t("No algorithm uses it yet.")}</p></section>;
  return <section className="panel"><div className="blk-table-wrap"><table className="table">
    <thead><tr><th>{t("Algorithm")}</th><th>{t("Made by")}</th><th>{t("Version it uses")}</th></tr></thead>
    <tbody>{block.used_by.map((item) => <tr key={`${item.algorithm_id}-${item.block_id}`}>
      <td><Link to={`/algorithms/${encodeURIComponent(item.algorithm_id)}`}><b>{item.name}</b></Link></td>
      <td>{item.system ? t("PlantCraft") : t("This site")}</td>
      <td>{item.number !== null ? <span className={`tag${item.current ? "" : " tag-old"}`}>{item.current ? t("version {number}", { number: item.number }) : t("version {number}, a newer one exists", { number: item.number })}</span> : <span className="muted">—</span>}</td>
    </tr>)}</tbody>
  </table></div></section>;
}

/** The block's own documentation: how it works, how to read it, its formula and its limits. */
function About({ block }: { block: BlockDetail }) {
  const list = (title: string, items: string[]) => items.length > 0 && <><h3>{title}</h3><ul>{items.map((item) => <li key={item}>{item}</li>)}</ul></>;
  const text = (title: string, body: string | null | undefined) => body && <><h3>{title}</h3><p>{body}</p></>;
  // Every block reads the same: What it does, How to read it, then the
  // Formula where the block computes one (an input or an output block has none).
  return <section className="panel blk-about">
    <div className="panel-header"><div><h2>{t("About this block")}</h2></div></div>
    {text(t("What it does"), block.description || block.summary)}
    {text(t("How to read it"), block.reading)}
    {block.formula && <><h3>{t("Formula")}</h3><pre className="blk-formula">{block.formula}</pre></>}
    {list(t("Assumptions"), block.assumptions)}
    {list(t("Limitations"), block.limitations)}
    {list(t("References"), block.references)}
  </section>;
}

/** The page of one version: `?version=N`, none for the one in use (where the page opens). */
export function versionAddress(base: string, number: number, block: Pick<BlockDetail, "in_use">): string {
  return number === block.in_use ? base : `${base}?version=${number}`;
}

/** Shown above the tabs while the page shows a version that is not the one in use (D17). */
function ShownVersion({ block, base, me, onSelected }: { block: BlockDetail; base: string; me: Me; onSelected: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!block.site || block.current || block.number === null) return null;
  const item = (block.versions ?? []).find((version) => version.number === block.number);
  async function select() {
    setBusy(true);
    setError("");
    try {
      await api.selectBlockVersion(block.family, block.number!);
      forgetBlockCatalog();
      navigate(base);
      onSelected();
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); } finally { setBusy(false); }
  }
  return <div className="notice blk-shown" role="status">
    <div>
      <b>{t("Showing version {number} of {name}", { number: block.number, name: block.name })}{item?.name ? ` · ${item.name}` : ""}</b>
      <p className="small">{t("Version {number} is the one in use: new algorithms and the palette take it. Algorithms keep the version they name.", { number: block.in_use ?? "?" })}</p>
      {error && <p className="small" role="alert">{error}</p>}
    </div>
    <div className="row-actions">
      <Link to={base} className="button button-secondary button-small">{t("Back to version {number}", { number: block.in_use ?? "?" })}</Link>
      {canWriteBlocks(me) && <button type="button" className="button button-primary button-small" disabled={busy} onClick={() => void select()}>{t("Select this version")}</button>}
    </div>
  </div>;
}

/** One calculation, the code the block runs; a version after the first compares with the one before. */
function CodeTab({ block, version }: { block: BlockDetail; version?: number }) {
  const [code, setCode] = useState<BlockCode | null>(null);
  const [diff, setDiff] = useState<ReturnType<typeof lineDiff> | null>(null);
  const [error, setError] = useState("");
  const shown = version ?? (block.site ? block.number ?? 1 : 1);
  useEffect(() => {
    setDiff(null);
    api.blockCode(pageId(block), version).then(setCode).catch((err: Error) => setError(err.message));
  }, [block, version]);
  if (error) return <ErrorBox text={error} />;
  if (!code) return <Loading />;
  const source = code.sources[0];
  async function compare() {
    setError("");
    try {
      const [before, after] = await Promise.all([api.blockCode(pageId(block), shown - 1), api.blockCode(pageId(block), shown)]);
      setDiff(lineDiff(before.sources[0]?.source ?? "", after.sources[0]?.source ?? ""));
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }
  return <section className="panel blk-source">
    <div className="panel-header"><div>
      <h2>{t("Version {number}", { number: shown })}</h2>
      <p>{code.site
        ? t("It runs in a separate, restricted process: no files, no network, limited time and memory.")
        : t("The code Analytics ships for this block, read-only.")}</p>
    </div>
      {shown > 1 && block.site && <div className="row-actions"><button type="button" className="button button-secondary button-small" onClick={() => void (diff ? setDiff(null) : compare())}>{diff ? t("Show the code") : t("Compare with {number}", { number: shown - 1 })}</button></div>}
    </div>
    {diff
      ? <CodeDiff lines={diff} />
      : source && <CodeEditor value={source.source} readOnly label={source.title} reveal={{ line: source.line }} />}
  </section>;
}

/** The contract in one list: inputs, outputs and parameters with their defaults. Changing any of
 * them is New version, which saves the next version (round 9: no separate defaults form here). */
function InputsTab({ block, method, newVersion }: { block: BlockDetail; method: MethodSpec | null; newVersion: string | null }) {
  return <section className="panel"><div className="panel-header"><div><h2>{t("Inputs, outputs and parameters")}</h2><p>{t("A wire joins an output to an input of the same type. An algorithm can change any parameter on its own block in the diagram; changing the block itself is a new version.")}</p></div></div>
    <ContractTable block={block} />
    {(method || newVersion) && <div className="row-actions">
      {newVersion && <Link to={newVersion} className="button button-secondary"><PenLine size={16} />{t("Change them in a new version")}</Link>}
      {method && <Link to={`/methods/${encodeURIComponent(method.method_id)}`} className="button button-secondary"><SlidersHorizontal size={16} />{t("This site's defaults")}</Link>}
    </div>}
  </section>;
}

/**
 * `/blocks/<id>[/inputs|code|test|used-by|versions|edit][?version=N]`: one block, as the editor's
 * inspector and the assistant read it, at the version in use or the one asked for. The tabs are
 * the same as an algorithm's; New version makes the next one, Duplicate a new block.
 */
export function BlockPage({ blockId, tab, me }: { blockId: string; tab: BlockTab; me: Me }) {
  const [block, setBlock] = useState<BlockDetail | null>(null);
  const [method, setMethod] = useState<MethodSpec | null>(null);
  const [model, setModel] = useState<ModelRow | null>(null);
  const [library, setLibrary] = useState("");
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(0);
  const [code, setCode] = useState("");
  // The block as its works read it (app.toml: each keeps the facts it needs): its ports,
  // parameters, code, versions and the algorithms that use it.
  useAssistantPage({ subject: linkRef("block", blockId), title: block?.name ?? blockId, place: t("Analytics › Block {name}", { name: block?.name ?? blockId }), page: "linkcraft:block", platformUrl: me.processcraft_url,
    facts: block ? { block: blockId, tab, name: block.name, summary: block.summary,
      inputs: block.inputs.map((port) => `${port.port} (${port.type}): ${port.label || port.description}`),
      outputs: block.outputs.map((port) => `${port.port} (${port.type}): ${port.label || port.description}`),
      parameters: block.parameters.map((item) => `${item.name} = ${JSON.stringify(item.default)}: ${item.title || item.description}`),
      used_by: block.used_by.map((use) => `${use.name} (${use.algorithm_id}, version ${use.number ?? "Link's"})`),
      versions: (block.versions ?? []).map((item) => `${item.number} ${item.name}`), code: code.slice(0, 4000) } : { block: blockId, tab } });
  // Back from the edit page, the block is read again: it has a new version.
  const editing = tab === "edit";
  const version = Number(new URLSearchParams(window.location.search).get("version")) || undefined;
  useEffect(() => {
    if (editing) return;
    setError("");
    api.block(blockId, version).then(setBlock).catch((err: Error) => setError(err.message));
    api.blockCode(blockId, version).then((found) => setCode(found.sources.map((item) => item.source).join("\n\n"))).catch(() => setCode(""));
  }, [blockId, loaded, editing, version]);
  useEffect(() => {
    blockCatalog().then((found) => setLibrary(found.libraries.find((item) => item.library === blockId.split(".")[0])?.name ?? "")).catch(() => undefined);
    api.methods().then((items) => setMethod(items.find((item) => item.block_id === blockId) ?? null)).catch(() => setMethod(null));
    if (blockId.startsWith("model.fmu_")) api.models().then((items) => setModel(items.find((item) => item.block_id === blockId) ?? null)).catch(() => setModel(null));
  }, [blockId]);
  if (tab === "edit") return <EditBlockPage blockId={blockId} me={me} />;
  if (error) return <ErrorBox text={error} />;
  if (!block) return <Loading />;
  const base = `/blocks/${encodeURIComponent(blockId)}`;
  // The tabs keep the version shown.
  const at = version ? `?version=${version}` : "";
  const shownNumber = block.site ? block.number ?? undefined : undefined;
  const writer = canWriteBlocks(me);
  const editable = canNewVersion(block, writer);
  const newVersion = editable ? `${base}/edit${at}` : null;
  // A block reading what Link gives it during a run (an input, an output, a loop's method)
  // has no code of its own to copy.
  const copyable = block.site || Boolean(block.copyable);
  const edited = block.site && (block.versions ?? []).some((item) => item.shipped);
  async function remove() {
    const question = edited
      ? t("Delete this site's versions of {name} and go back to Analytics' version? This cannot be undone.", { name: block!.name })
      : t("Delete {name} and all its versions? This cannot be undone.", { name: block!.name });
    if (!(await confirmAction(question, { confirm: t("Delete"), danger: true }))) return;
    try {
      await api.deleteBlock(block!.family);
      forgetBlockCatalog();
      if (edited) { navigate(base); setLoaded((now) => now + 1); } else navigate(`/blocks?library=${encodeURIComponent(block!.library)}`);
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }
  return <>
    <nav className="breadcrumb"><Link to={`/blocks?library=${encodeURIComponent(block.library)}`}>{library || t("Blocks")}</Link><ChevronRight size={12} /><span>{block.name}</span></nav>
    <Heading eyebrow={<>{!block.site && <Lock size={12} className="blk-lock" aria-label={t("Ships with PlantCraft")} />}{`${library || block.library} · ${pageId(block)} · ${madeBy(block)}`}</>} title={block.name} detail={block.summary}
      actions={<>
        {me.can_edit && (copyable
          ? <Link to={`/blocks/new?from=${encodeURIComponent(pageId(block))}${version ? `&version=${version}` : ""}`} className="button button-secondary"><Copy size={16} />{t("Duplicate")}</Link>
          : <button type="button" className="button button-secondary" disabled title={t("This block reads what Analytics gives it during a run: it has no code of its own to copy.")}><Copy size={16} />{t("Duplicate")}</button>)}
        <button type="button" className="button button-secondary" onClick={() => void api.blockFile(pageId(block), shownNumber).then(downloadBlockFile).catch((err: Error) => setError(err.message))}><Download size={16} />{t("Download the file")}</button>
        {block.site && writer && !block.used_by.length && <button type="button" className="button button-secondary" onClick={() => void remove()}><Trash2 size={16} />{edited ? t("Back to Analytics' version") : t("Delete")}</button>}
        {model && me.can_edit && <button type="button" className="button button-secondary" onClick={() => openEditor(null, undefined, model.model_id)}><Plus size={16} />{t("New algorithm with this model")}</button>}
      </>} />
    <ShownVersion block={block} base={base} me={me} onSelected={() => setLoaded((now) => now + 1)} />
    <PageTabs label={t("Block")} href={href} navigate={navigate} tabs={[
      { to: `${base}${at}`, label: t("Overview"), active: tab === "overview" },
      { to: `${base}/inputs${at}`, label: t("Inputs and outputs"), active: tab === "inputs" },
      { to: `${base}/code${at}`, label: t("Code"), active: tab === "code" },
      { to: `${base}/test${at}`, label: t("Test"), active: tab === "test" },
      { to: `${base}/used-by${at}`, label: t("Used by ({count})", { count: block.used_by.length }), active: tab === "used-by" },
      { to: `${base}/versions${at}`, label: t("Versions ({count})", { count: block.site ? (block.versions ?? []).length : 1 }), active: tab === "versions" },
      ...(tab === "compare" ? [{ to: `${base}/compare${window.location.search}`, label: t("Compare"), active: true }] : []),
    ]} />
    <div className="blk-tab">
      {tab === "overview" && <section className="panel blk-drawing" aria-label={t("How it is drawn")}><BlockDrawing spec={block} caption={t("As it is drawn in an algorithm: inputs on the left, outputs on the right.")} /></section>}
      {tab === "overview" && <About block={block} />}
      {tab === "code" && <CodeTab block={block} version={shownNumber} />}
      {tab === "inputs" && <InputsTab block={block} method={method} newVersion={newVersion} />}
      {tab === "test" && <BlockTest subject={{ block_id: block.block_id }} inputs={block.inputs} outputs={block.outputs} />}
      {tab === "used-by" && <UsedBy block={block} />}
      {tab === "versions" && <BlockVersions block={block} base={base} me={me} newVersion={newVersion} onSaved={() => setLoaded((now) => now + 1)} />}
      {tab === "versions" && block.site && <ComparePicker numbers={(block.versions ?? []).map((item) => item.number)} base={base} />}
      {tab === "compare" && <BlockCompare block={block} />}
    </div>
  </>;
}
