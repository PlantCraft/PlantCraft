/**
 * `/blocks`: what a model's diagram is drawn with, by library (Sources, Math, Continuous,
 * Control, Process equipment, Sinks, and the site's own), like Analytics' Blocks.
 * `/blocks/<class>[/<tab>]`: one block on the tabs Analytics' blocks have:
 * Overview (its drawing and what it does, how to read it, its formula), Inputs and outputs (with
 * its parameters; a site block's defaults change there, as a new version), Code, Used by and
 * Versions. The shipped libraries are read-only; Duplicate copies any block into the site's own
 * library, and a library of the site's own is written in the code editor (New block library).
 */
import { ParameterField, typeLabel, type BlockCatalog, type DiagramNode, type PortSpec } from "@plantcraft/ui/blockEditor";
import { BlockDrawing, BlockImageField, chosenFolder, ComparePicker, FolderButton, FolderColumn, folderName, FolderPlaceLine, inFolder, NO_FOLDER, PageTabs, rememberFolder, useFolders, VersionsTab } from "@plantcraft/ui";
import { Code2, Copy, Puzzle, Save, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { t } from "./i18n";
import { href, navigate } from "./nav";
import { blockPath, codePath, modelPath, type BlockTab } from "./paths";
import { modelVersions, VersionDialog } from "./ModelPage";
import { BlockCompare } from "./Versions";
import type { BlockLibrary, BlockUse, CatalogBlock, Me, Revision } from "./types";
import { Dialog, ErrorBox, Heading, Link, Loading, message } from "./ui";

/** The library a Blocks page opens on: ?library= in the address, else the first. */
export function chosenLibrary(libraries: Array<{ library: string }>, search: string): string {
  const asked = new URLSearchParams(search).get("library");
  return libraries.find((item) => item.library === asked)?.library ?? libraries[0]?.library ?? "";
}

function Ports({ ports }: { ports: PortSpec[] }) {
  if (!ports.length) return <span className="muted">–</span>;
  return <span className="blk-ports">{ports.map((port) => <span key={port.port} className="blk-port" title={port.description}>{port.label || port.port}</span>)}</span>;
}

function LibraryDialog({ groups, onClose }: { groups: string[]; onClose: () => void }) {
  const [name, setName] = useState("");
  const [group, setGroup] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try { const library: BlockLibrary = await api.createLibrary(name.trim(), group.trim(), ""); navigate(codePath(library.id)); } catch (err) { setError(message(err)); setBusy(false); }
  };
  return <Dialog title={t("New block library")} onClose={onClose} footer={<>
    <button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button>
    <button type="button" className="button button-primary" disabled={busy || !name.trim()} onClick={() => void save()}>{t("Create")}</button>
  </>}>
    {error && <div className="notice notice-error">{error}</div>}
    <p className="muted small">{t("A Modelica package of blocks every model can use, written in the code editor. A block's real inputs and outputs become its ports in the diagram; its parameters, its settings.")}</p>
    <div className="form-grid">
      <label>{t("Name")}<input value={name} maxLength={120} autoFocus onChange={(event) => setName(event.target.value)} placeholder={t("e.g. Heat exchangers")} /></label>
      <label>{t("Category")} <small>{t("optional")}</small><input list="mc-block-groups" value={group} maxLength={60} onChange={(event) => setGroup(event.target.value)} placeholder={t("e.g. Equipment")} />
        <datalist id="mc-block-groups">{groups.filter(Boolean).map((item) => <option key={item} value={item} />)}</datalist></label>
    </div>
  </Dialog>;
}

export function BlocksPage({ me }: { me: Me }) {
  const [catalog, setCatalog] = useState<BlockCatalog | null>(null);
  const [current, setCurrent] = useState("");
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  // Folders of the site's own blocks (round 9, M5), as Link's: the libraries stay above them.
  const [folders, reloadFolders] = useFolders("block");
  const [folder, setFolder] = useState(() => chosenFolder(window.location.search));
  useEffect(() => { api.catalog().then((found) => { setCatalog(found); setCurrent(chosenLibrary(found.libraries, window.location.search)); }).catch((err) => setError(message(err))); }, []);
  const words = query.trim().toLowerCase();
  const matches = useMemo(() => (block: BlockCatalog["blocks"][number]) => !words || `${block.name} ${block.block_id} ${block.summary} ${block.group ?? ""}`.toLowerCase().includes(words), [words]);
  if (error) return <ErrorBox text={error} />;
  if (!catalog) return <Loading />;
  const choose = (library: string) => { setCurrent(library); setFolder(""); window.history.replaceState({}, "", href(`/blocks?library=${encodeURIComponent(library)}`)); };
  const library = catalog.libraries.find((item) => item.library === current) ?? catalog.libraries[0];
  const own = new Set(catalog.libraries.filter((item) => (item as { own?: boolean }).own).map((item) => item.library));
  const siteBlocks = catalog.blocks.filter((block) => own.has(block.library));
  const chooseFolder = (value: string) => { setQuery(""); setFolder(value); rememberFolder("/blocks", value); };
  const shown = words ? catalog.blocks.filter(matches)
    : folder ? siteBlocks.filter((block) => inFolder(folders, block.block_id, folder))
    : catalog.blocks.filter((block) => block.library === library?.library);
  return <>
    <Heading title={t("Blocks")} actions={me.can_edit ? <button type="button" className="button button-secondary" onClick={() => setCreating(true)}><Puzzle />{t("New block library")}</button> : undefined} />
    <label className="mc-block-search"><Search size={15} /><input type="search" value={query} placeholder={t("Search blocks")} aria-label={t("Search blocks")} onChange={(event) => setQuery(event.target.value)} /></label>
    <div className="pc-folder-layout">
      <FolderColumn kind="block" list={folders} chosen={words ? "-" : folder} onChoose={chooseFolder} total={siteBlocks.length} canEdit={me.can_edit} onChanged={reloadFolders} label={t("Libraries and folders")}
        before={catalog.libraries.map((item) => <FolderButton key={item.library} active={!words && !folder && item.library === library?.library} onClick={() => { setQuery(""); choose(item.library); }} count={item.count ?? 0}>{item.name}</FolderButton>)} />
      <section>
        {words ? <h2 className="section-title">{t("{n} blocks found", { n: shown.length })}</h2>
          : folder ? <div className="mc-library-head"><h2>{folderName(folders, folder)}</h2><p className="muted">{folder === NO_FOLDER ? t("This site's blocks that are in no folder.") : t("This site's blocks in this folder. Move a block with Move to folder on its page.")}</p></div>
          : library && <div className="mc-library-head"><h2>{library.name}</h2>{library.description && <p className="muted">{library.description}</p>}</div>}
        {shown.length ? <div className="pc-grid">{shown.map((block) => <Link key={block.block_id} to={blockPath(block.block_id)} className="panel card mc-block-card">
          <strong>{block.name}</strong><p>{block.summary}</p>
          <small className="blk-card-ports">{block.inputs.length > 0 && <span><b>{t("In")}</b><Ports ports={block.inputs} /></span>}{block.outputs.length > 0 && <span><b>{t("Out")}</b><Ports ports={block.outputs} /></span>}</small>
        </Link>)}</div> : <div className="panel empty"><p>{t("No block matches.")}</p></div>}
      </section>
    </div>
    {creating && <LibraryDialog groups={[...new Set(catalog.libraries.map((item) => (item as { group?: string }).group ?? ""))]} onClose={() => setCreating(false)} />}
  </>;
}

/** Inputs, outputs and parameters in one table, so their columns line up (as Link's blocks). */
function ContractTable({ block, parameters = true }: { block: CatalogBlock; parameters?: boolean }) {
  const port = (item: PortSpec) => <tr key={`${item.port}`}>
    <td><b>{item.label || item.port}</b><small className="pc-mono">{item.port}</small></td>
    <td>{typeLabel(item.type)}</td><td>{item.unit || "–"}</td>
    <td>{item.description !== item.label ? item.description : ""}</td>
  </tr>;
  const group = (title: string, count: number) => <tr className="mc-contract-group"><th colSpan={4}>{title} ({count})</th></tr>;
  return <section className="panel" aria-label={t("Inputs, outputs and parameters")}>
    <table className="table mc-contract"><colgroup><col className="mc-col-name" /><col className="mc-col-type" /><col className="mc-col-unit" /><col /></colgroup>
      <thead><tr><th>{t("Name")}</th><th>{t("Type")}</th><th>{t("Unit / default")}</th><th>{t("Description")}</th></tr></thead>
      <tbody>
        {group(t("Inputs"), block.inputs.length)}{block.inputs.map(port)}
        {group(t("Outputs"), block.outputs.length)}{block.outputs.map(port)}
        {parameters && <>{group(t("Parameters"), block.parameters.length)}{block.parameters.map((item) => <tr key={`p-${item.name}`}>
          <td><b className="pc-mono">{item.name}</b>{item.title && item.title !== item.name && <small>{item.title}</small>}</td>
          <td>{String(item.schema?.type ?? "")}</td>
          <td className="pc-mono">{JSON.stringify(item.default)}{item.unit && ` ${item.unit}`}</td>
          <td>{item.description}</td>
        </tr>)}</>}
      </tbody>
    </table>
  </section>;
}

function UsedBy({ blockId }: { blockId: string }) {
  const [models, setModels] = useState<BlockUse[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.blockUsedBy(blockId).then(setModels).catch((err) => setError(message(err))); }, [blockId]);
  if (error) return <ErrorBox text={error} />;
  if (!models) return <Loading />;
  return <section className="panel" aria-label={t("Used by")}>
    <h2>{t("Models that use it")}</h2>
    {models.length === 0 ? <p className="muted">{t("No model uses this block yet.")}</p>
      : <table className="table"><thead><tr><th>{t("Model")}</th><th>{t("Times placed")}</th></tr></thead><tbody>{models.map((item) => <tr key={`${item.project_id}/${item.model}`}>
        <td><Link to={modelPath(item.project_id, item.model)}><b>{item.name}</b></Link>{item.example && <small>{t("Example")}</small>}</td>
        <td className="pc-num">{item.count}</td>
      </tr>)}</tbody></table>}
  </section>;
}

/** The block's own documentation, as Analytics' blocks show it: what it does, how to read it and
 * its formula (the parts of its Documentation annotation). */
function AboutBlock({ block }: { block: CatalogBlock }) {
  const text = (title: string, body: string | null | undefined) => body && <><h3>{title}</h3><p>{body}</p></>;
  return <section className="panel mc-block-about" aria-label={t("About this block")}>
    <h2>{t("About this block")}</h2>
    {text(t("What it does"), block.description || block.summary)}
    {text(t("How to read it"), block.reading)}
    {block.formula && <><h3>{t("Formula")}</h3><pre className="mc-formula">{block.formula}</pre></>}
    <p className="muted small">{t("Written in its code (the class comment and its documentation): the diagram's inspector and the assistant read it from there.")}</p>
  </section>;
}

function BlockAbout({ block }: { block: CatalogBlock }) {
  return <section className="panel mc-about" aria-label={t("About it")}>
    <h2>{t("About it")}</h2>
    <dl className="mc-facts">
      <div><dt>{t("Library")}</dt><dd><Link to={`/blocks?library=${encodeURIComponent(block.library)}`}>{block.library_name}</Link></dd></div>
      <div><dt>{t("Class")}</dt><dd className="pc-mono">{block.block_id}</dd></div>
      <div><dt>{t("Made by")}</dt><dd>{block.example ? t("Models ships it") : t("This site")}</dd></div>
      {block.file && <div><dt>{t("File")}</dt><dd className="pc-mono">{block.file}</dd></div>}
    </dl>
  </section>;
}

/** A block's versions: what it is on top, then each save of its library file (round 9). */
function BlockVersions({ block, revisions }: { block: CatalogBlock; revisions: Revision[] | null }) {
  const count = (revisions?.length ?? 0) + 1;
  return <><VersionsTab about={<BlockAbout block={block} />}
    versions={revisions === null ? null : modelVersions(revisions, block.example ? {} : { by: block.updated_by, at: block.updated_at, name: block.version_name, note: block.version_note })}
    footer={block.example ? t("A block Models ships: it changes with Models' versions.") : t("Saving its code makes a new version.")} />
    {revisions && <ComparePicker numbers={Array.from({ length: count }, (_, index) => index + 1)} text={t("Tick two or three versions: their inputs, outputs and parameters side by side, and what changed in the code.")}
      onCompare={(ticked) => navigate(`${blockPath(block.block_id, "compare")}?versions=${ticked.join(",")}`)} />}
  </>;
}

/** The block as a diagram draws it, and its picture (round 9 M1, M2): the site's own blocks
 * take one, written in the class's Icon annotation, so it is saved as a new version. */
function BlockPicture({ block, canEdit, onChanged }: { block: CatalogBlock; canEdit: boolean; onChanged: (block: CatalogBlock) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function save(image: string) {
    setBusy(true); setError("");
    try { onChanged(await api.setBlockImage(block.block_id, image)); } catch (err) { setError(message(err)); } finally { setBusy(false); }
  }
  return <section className="panel mc-block-drawing" aria-label={t("How it is drawn")}>
    <BlockDrawing spec={block} caption={t("As it is drawn in a model: inputs on the left, outputs on the right.")} />
    {canEdit && <div className="mc-block-image">
      <h3>{t("Image")}</h3>
      <BlockImageField id="mc-block-image" value={block.image ?? ""} disabled={busy} onChange={(image) => void save(image)} />
      <p className="muted small">{t("Kept in the class's Icon annotation (a Bitmap): changing it saves a new version of the library file.")}</p>
    </div>}
    {error && <ErrorBox text={error} />}
  </section>;
}

/** Inputs, outputs and parameters; a site block's defaults change here and saving is a new
 * version with what changed. A model that sets its own value keeps it. */
function InputsTab({ block, canEdit, onSaved }: { block: CatalogBlock; canEdit: boolean; onSaved: (block: CatalogBlock) => void }) {
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [naming, setNaming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const node = { id: "defaults", block: block.block_id, parameters: draft } as unknown as DiagramNode;
  const changed = Object.fromEntries(Object.entries(draft).filter(([name, value]) => value !== undefined && JSON.stringify(value) !== JSON.stringify(block.parameters.find((item) => item.name === name)?.default)));
  const dirty = Object.keys(changed).length > 0;
  async function save(name: string, note: string) {
    setBusy(true); setError("");
    try { onSaved(await api.setBlockDefaults(block.block_id, changed, { name, note }, block.updated_at ?? null)); setDraft({}); setNaming(false); } catch (err) { setError(message(err)); } finally { setBusy(false); }
  }
  return <>
    <section className="panel"><div className="panel-header"><div><h2>{t("Inputs, outputs and parameters")}</h2>
      <p>{t("A wire joins an output to an input. A model can set its own value for any parameter on its block in the diagram; the default is the block's, and a study can set another for each simulation.")}</p></div></div></section>
    <ContractTable block={block} />
    {canEdit && block.parameters.length > 0 && <section className="panel mc-node-parameters" aria-label={t("Defaults")}>
      <h2>{t("Defaults")}</h2>
      <p className="muted small">{t("Change a default and save: the block's code changes and makes a new version.")}</p>
      <div className="mc-node-fields">{block.parameters.map((parameter) => <ParameterField key={parameter.name} node={node} parameter={parameter} readOnly={busy} onSet={(value) => setDraft({ ...draft, [parameter.name]: value })} />)}</div>
      {error && <ErrorBox text={error} />}
      <div className="row-actions">
        <button type="button" className="button button-secondary" disabled={busy || !dirty} onClick={() => setDraft({})}>{t("Undo the changes")}</button>
        <button type="button" className="button button-primary" disabled={busy || !dirty} onClick={() => { setError(""); setNaming(true); }}><Save size={16} />{t("Save as a new version")}</button>
      </div>
    </section>}
    {block.example && <p className="muted small">{t("A block Models ships keeps its defaults: Duplicate makes a copy in this site's library to change.")}</p>}
    {naming && <VersionDialog next={0} title={t("Save as a new version")} busy={busy} error={error} onClose={() => setNaming(false)} onSave={(name, note) => void save(name, note)} />}
  </>;
}

/** Duplicate: a copy of the block, under a new name, in this site's own library. */
function DuplicateDialog({ block, onClose }: { block: CatalogBlock; onClose: () => void }) {
  const [name, setName] = useState(t("{name} copy", { name: block.name }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function save() {
    setBusy(true);
    try { const copy = await api.duplicateBlock(block.block_id, name.trim()); navigate(blockPath(copy.block_id)); } catch (err) { setError(message(err)); setBusy(false); }
  }
  return <Dialog title={t("Duplicate {name}", { name: block.name })} onClose={onClose} footer={<>
    <button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button>
    <button type="button" className="button button-primary" disabled={busy || !name.trim()} onClick={() => void save()}><Copy size={16} />{t("Duplicate")}</button>
  </>}>
    {error && <div className="notice notice-error">{error}</div>}
    <p className="muted small">{t("A copy in this site's own library, with the same code: change its defaults, its picture and its code there.")}</p>
    <div className="form-grid"><label>{t("Name")}<input id="mc-copy-name" value={name} maxLength={120} autoFocus onChange={(event) => setName(event.target.value)} /></label></div>
  </Dialog>;
}

/** One block on the pages Link's blocks have: Overview, Code, Inputs and
 * parameters, Used by and Versions (what it is, then its versions; round 9). */
export function BlockPage({ blockId, tab, me }: { blockId: string; tab: BlockTab; me: Me }) {
  const [block, setBlock] = useState<CatalogBlock | null>(null);
  const [revisions, setRevisions] = useState<Revision[] | null>(null);
  const [error, setError] = useState("");
  const [copying, setCopying] = useState(false);
  useEffect(() => { api.catalogBlock(blockId).then(setBlock).catch((err) => setError(message(err))); }, [blockId]);
  useEffect(() => {
    if (!block) return;
    if (!block.file) { setRevisions([]); return; }
    api.revisions(block.library, block.file).then(setRevisions).catch(() => setRevisions([]));
  }, [block]);
  if (error) return <ErrorBox text={error} />;
  if (!block) return <Loading />;
  const base = blockPath(blockId);
  return <>
    <nav className="breadcrumb"><Link to="/blocks">{t("Blocks")}</Link> › <Link to={`/blocks?library=${encodeURIComponent(block.library)}`}>{block.library_name}</Link></nav>
    <Heading eyebrow={<span className="pc-mono">{block.block_id}</span>} title={block.name} detail={block.summary}
      actions={me.can_edit ? <>
        <button type="button" className="button button-secondary" onClick={() => setCopying(true)}><Copy size={16} />{t("Duplicate")}</button>
        {!block.example && <Link to={codePath(block.library, block.block_id)} className="button button-secondary"><Code2 size={16} />{t("Edit the code")}</Link>}
      </> : undefined} />
    {!block.example && tab === "overview" && <FolderPlaceLine kind="block" itemId={block.block_id} canEdit={me.can_edit} />}
    <PageTabs label={t("Block")} href={href} navigate={navigate} tabs={[
      { to: base, label: t("Overview"), active: tab === "overview" },
      { to: blockPath(blockId, "inputs"), label: t("Inputs and outputs"), active: tab === "inputs" },
      { to: blockPath(blockId, "code"), label: t("Code"), active: tab === "code" },
      { to: blockPath(blockId, "used-by"), label: t("Used by"), active: tab === "used-by" },
      { to: blockPath(blockId, "versions"), label: revisions ? t("Versions ({count})", { count: revisions.length + 1 }) : t("Versions"), active: tab === "versions" || tab === "compare" },
    ]} />
    <div className="mc-page mc-tab">
      <div className="mc-page-main">
        {tab === "overview" && <>
          <BlockPicture block={block} canEdit={!block.example && me.can_edit} onChanged={(found) => { setBlock(found); setRevisions(null); }} />
          <AboutBlock block={block} />
        </>}
        {tab === "code" && <section className="panel"><h2>{t("Code")}</h2>
          {block.example && <p className="muted small">{t("A block Models ships: its code is read-only.")}</p>}
          <pre className="mc-code">{block.code}</pre>
        </section>}
        {tab === "inputs" && <InputsTab key={block.updated_at ?? ""} block={block} canEdit={!block.example && me.can_edit} onSaved={(found) => { setBlock(found); setRevisions(null); }} />}
        {tab === "used-by" && <UsedBy blockId={blockId} />}
        {tab === "versions" && <BlockVersions block={block} revisions={revisions} />}
        {tab === "compare" && <BlockCompare block={block} revisions={revisions} />}
      </div>
    </div>
    {copying && <DuplicateDialog block={block} onClose={() => setCopying(false)} />}
  </>;
}
