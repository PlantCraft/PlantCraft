/**
 * Making a block: `/blocks/new` (import a block file or fill in the form; the assistant's button
 * beside the title opens it on writing a block, owner 2026-10-25, round 9) and `/blocks/<id>/edit`
 * (the next version of a block, a block Link ships included). Saving a version asks for its name
 * and what changed (owner, 2026-10-23).
 */
import { Dialog, useAssistantPage } from "@plantcraft/ui";
import { ChevronRight, FileUp, FormInput, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "./api";
import { forgetBlockCatalog, blockCatalog } from "./AlgorithmEditor";
import { blockFromDraft, changedFromDraft, contractChanged, newBlockFile, parseBlockFile } from "./blockFile";
import { assistantDraft } from "./Assistant";
import { BlockForm, type FormLibrary } from "./BlockForm";
import { BlockTest } from "./BlockTest";
import { t } from "./i18n";
import { navigate } from "./nav";
import type { BlockCheck, BlockFileDoc, Me } from "./types";
import { ErrorBox, Heading, Link, Loading } from "./ui";

/** The suite's reference the assistant reads before it writes a block (`knowledge.new_block_item`). */
export const NEW_BLOCK_REF = "block:linkcraft/new";

export const canWriteBlocks = (me: Me) => me.can_edit && me.is_admin;

/** The libraries a block may join (Link's open ones and the site's), and one made just now. */
function useLibraries(): [FormLibrary[], (made: FormLibrary) => void] {
  const [found, setFound] = useState<FormLibrary[]>([]);
  useEffect(() => {
    blockCatalog().then((catalog) => setFound(catalog.libraries.filter((item) => (catalog.open_libraries ?? []).includes(item.library)).map((item) => ({ library: item.library, name: item.name })))).catch(() => setFound([{ library: "custom", name: t("Site blocks") }]));
  }, []);
  return [found, (made) => setFound((now) => [...now.filter((item) => item.library !== made.library), made])];
}

/** Checks a file as people type (after a pause): its contract, then its code. */
function useCheck(file: BlockFileDoc | null): BlockCheck | null {
  const [check, setCheck] = useState<BlockCheck | null>(null);
  useEffect(() => {
    if (!file) return;
    const timer = window.setTimeout(() => { api.checkBlock(file).then(setCheck).catch((err: Error) => setCheck({ valid: false, problems: [err.message] })); }, 450);
    return () => window.clearTimeout(timer);
  }, [file]);
  return check;
}

function Problems({ check }: { check: BlockCheck | null }) {
  if (!check) return <p className="muted small">{t("Checking…")}</p>;
  if (check.valid) return <p className="blkf-ok small">{t("The block is valid: its contract and its code pass the checks.")}</p>;
  return <div className="notice notice-error" role="alert"><b>{t("To fix before saving:")}</b><ul>{check.problems.map((item, index) => <li key={index}>{item}</li>)}</ul></div>;
}

function SaveDialog({ title, check, first, busy, error, who, onClose, onSave }: {
  title: string; check: BlockCheck | null; first: boolean; busy: boolean; error: string; who: string;
  onClose: () => void; onSave: (name: string, description: string) => void;
}) {
  const [name, setName] = useState(first ? t("First version") : "");
  const [description, setDescription] = useState("");
  return <Dialog title={title} onClose={onClose} onSubmit={(event) => { event.preventDefault(); onSave(name.trim(), description.trim()); }}>
      {!first && check?.contract_changed && <div className="notice notice-warning">{t("This version changes the block's inputs or outputs. The algorithms that use it keep their version until someone updates them and rewires what changed.")}</div>}
      {!first && !!check?.used_by && <p className="muted small">{t("{count} algorithms use this block; each keeps the version it names until it is updated.", { count: check.used_by })}</p>}
      <div className="form-grid">
        <label>{t("Version name")}<input id="blk-version-name" value={name} required maxLength={120} onChange={(event) => setName(event.target.value)} placeholder={t("Adaptive window")} /></label>
        <label className="blkf-wide">{t("What changed")}<textarea id="blk-version-description" rows={3} value={description} maxLength={2000} onChange={(event) => setDescription(event.target.value)} /></label>
      </div>
      <p className="muted small">{t("Saved by {name}, with the date: the version's history shows who made each change.", { name: who })}</p>
      {error && <div className="notice notice-error" role="alert">{error}</div>}
      <footer><button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button><button className="button button-primary" disabled={busy || !name.trim()}><Save size={16} />{busy ? t("Saving…") : first ? t("Create the block") : t("Save as new version")}</button></footer>
  </Dialog>;
}

/** The form with its check, a test on an asset and the save. */
function Workbench({ start, me, existing, onCancel }: { start: BlockFileDoc; me: Me; existing?: { blockId: string; file: BlockFileDoc; next?: number }; onCancel: () => void }) {
  const [libraries, addLibrary] = useLibraries();
  const [file, setFile] = useState<BlockFileDoc>(start);
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [testing, setTesting] = useState(false);
  const check = useCheck(file);
  const changed = existing ? JSON.stringify({ ...file, version: null }) !== JSON.stringify({ ...existing.file, version: null }) : true;
  async function save(name: string, description: string) {
    setBusy(true);
    setError("");
    try {
      const saved = existing ? await api.saveBlockVersion(existing.blockId, file, name, description) : await api.createBlock(file, name, description);
      forgetBlockCatalog();
      navigate(`/blocks/${encodeURIComponent(saved.block_id)}`);
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); } finally { setBusy(false); }
  }
  const allowed = canWriteBlocks(me);
  return <>
    {!allowed && <div className="notice notice-warning">{t("Only administrators save block code, because it runs on the server. You can fill in the form, check and test it, and download the file for an administrator.")}</div>}
    <div className="blkf-bar panel">
      <Problems check={check} />
      <div className="row-actions">
        <button type="button" className="button button-secondary" onClick={() => setTesting(!testing)}>{testing ? t("Hide the test") : t("Test on an asset")}</button>
        <button type="button" className="button button-secondary" onClick={onCancel}>{t("Cancel")}</button>
        <button type="button" className="button button-primary" disabled={!allowed || !check?.valid || !changed} title={!changed ? t("Nothing changed yet.") : undefined} onClick={() => setSaving(true)}>
          <Save size={16} />{existing ? (existing.next ? t("Save as version {n}", { n: existing.next }) : t("Save as new version")) : t("Create the block")}
        </button>
      </div>
    </div>
    {testing && check?.valid && <BlockTest subject={file} inputs={file.inputs} outputs={file.outputs} parameters={Object.fromEntries(file.parameters.map((item) => [item.name, item.default]))} />}
    {testing && !check?.valid && <p className="muted small">{t("Fix the problems first, then test.")}</p>}
    <BlockForm file={file} libraries={libraries} problems={check?.problems ?? []} fixedLibrary={!!existing} onChange={setFile} onNewLibrary={addLibrary} onSave={() => { if (allowed && check?.valid && changed) setSaving(true); }} />
    {saving && <SaveDialog title={existing ? t("Save as new version") : t("Create the block")} check={existing ? { ...(check ?? { valid: true, problems: [] }), contract_changed: contractChanged(existing.file, file) } : check} first={!existing} busy={busy} error={error} who={me.name || me.username} onClose={() => setSaving(false)} onSave={(name, description) => void save(name, description)} />}
  </>;
}

function ImportStart({ onFile }: { onFile: (file: BlockFileDoc) => void }) {
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const use = (raw: string) => {
    try { onFile({ ...parseBlockFile(raw), origin: "import" }); } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  };
  return <section className="panel blkn-step">
    <h2>{t("Import a block file")}</h2>
    <p className="muted">{t("A JSON file in Analytics' block format (plantcraft-block/1): its code, description, inputs, outputs and parameters. It opens in the form to check before you save it.")}</p>
    <label className="button button-secondary blkn-upload"><FileUp size={16} />{t("Choose a file…")}<input type="file" accept=".json,application/json" onChange={(event) => { const chosen = event.target.files?.[0]; if (chosen) chosen.text().then(use).catch((err: Error) => setError(err.message)); }} /></label>
    <label className="blkn-paste">{t("Or paste it here")}<textarea id="blkn-import-text" rows={8} className="pc-mono" value={text} onChange={(event) => setText(event.target.value)} /></label>
    <div className="row-actions"><button type="button" className="button button-primary" disabled={!text.trim()} onClick={() => use(text)}>{t("Open in the form")}</button></div>
    {error && <div className="notice notice-error" role="alert">{error}</div>}
  </section>;
}

type Way = "import" | "form";

/** `/blocks/new` (and `?from=<block>` to start from a copy). */
export function NewBlockPage({ me }: { me: Me }) {
  const query = new URLSearchParams(window.location.search);
  const from = query.get("from");
  const fromVersion = Number(query.get("version")) || undefined;
  // A new block joins the library its list showed (round 10), when blocks may join it.
  const [library, setLibrary] = useState("");
  useEffect(() => {
    const asked = query.get("library") ?? "";
    if (asked) blockCatalog().then((catalog) => { if ((catalog.open_libraries ?? []).includes(asked)) setLibrary(asked); }).catch(() => undefined);
  }, []);
  // A block the assistant proposed starts the form filled in (its card's "Continue in the block form").
  const [drafted] = useState(() => { const draft = from ? null : assistantDraft("new-block", "block-variant"); return draft ? blockFromDraft(draft) : null; });
  const [way, setWay] = useState<Way | null>(drafted ? "form" : null);
  const [file, setFile] = useState<BlockFileDoc | null>(drafted);
  const [error, setError] = useState("");
  useEffect(() => { if (from) api.blockCopy(from, false, fromVersion).then(setFile).catch((err: Error) => setError(err.message)); }, [from, fromVersion]);
  useAssistantPage({
    subject: NEW_BLOCK_REF, title: t("A new block"), place: t("Analytics › New block"), platformUrl: me.processcraft_url, page: "linkcraft:block-new",
    prepare: () => api.prepareAssistant(NEW_BLOCK_REF),
    context: file ? t("The person is filling in a new block named {name}.", { name: file.name || t("(no name yet)") }) : t("The person is creating a new block in Analytics."),
  });
  const ways: Array<{ id: Way; icon: React.ReactNode; title: string; text: string }> = [
    { id: "import", icon: <FileUp size={20} />, title: t("Import a file"), text: t("A block file (JSON) with its code, description, inputs and outputs.") },
    { id: "form", icon: <FormInput size={20} />, title: t("Fill in the form"), text: t("Name, inputs, outputs, parameters and the Python code, field by field.") },
  ];
  return <>
    <nav className="breadcrumb"><Link to="/blocks">{t("Blocks")}</Link><ChevronRight size={12} /><span>{t("New block")}</span></nav>
    <Heading eyebrow={t("Algorithms and blocks")} title={file ? (file.name || t("New block")) : t("New block")}
      detail={file ? t("Check the form, test it on an asset, then create it: it becomes version 1.") : t("A block is one calculation with typed inputs and outputs, its parameters and its Python code. Every save is a new version with a name, and algorithms keep the version they use.")} />
    {error && <ErrorBox text={error} />}
    {file
      ? <Workbench start={file} me={me} onCancel={() => { setFile(null); if (from) navigate("/blocks/new"); }} />
      : from ? (error ? null : <Loading />) : <>
        <div className="pc-grid blkn-ways">{ways.map((item) => <button key={item.id} type="button" className={`panel card blkn-way${way === item.id ? " active" : ""}`} aria-pressed={way === item.id} onClick={() => { setWay(item.id); if (item.id === "form") setFile(library ? { ...newBlockFile(), library } : newBlockFile()); }}>
          <span className="blkn-way-icon">{item.icon}</span><strong>{item.title}</strong><p>{item.text}</p>
        </button>)}</div>
        {way === "import" && <ImportStart onFile={setFile} />}
      </>}
  </>;
}

/** `/blocks/<id>/edit[?version=N]`: New version, the form filled in from the version shown (the
 * one in use when none is), tested and saved as the block's next number (owner D16, 2026-10-26).
 * A block Link ships starts from Link's code and its first save on this site is version 2. */
export function EditBlockPage({ blockId, me }: { blockId: string; me: Me }) {
  const from = Number(new URLSearchParams(window.location.search).get("version")) || undefined;
  const [file, setFile] = useState<BlockFileDoc | null>(null);
  const [start, setStart] = useState<{ number: number; next: number } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.block(blockId, from).then(async (block) => {
      const versions = block.versions ?? [];
      const number = block.site ? block.number ?? 1 : 1;
      const shipped = !block.site || versions.some((item) => item.shipped && item.number === number);
      setStart({ number, next: Math.max(1, ...versions.map((item) => item.number)) + 1 });
      const current = await (shipped ? api.blockCopy(blockId, true, block.site ? number : undefined) : api.blockFile(blockId, number));
      // "Help me change this block" (app.toml): the assistant's new code and summary, on top of
      // the version shown; the person tests it and saves the next version.
      const draft = assistantDraft("change-block");
      setFile(draft ? changedFromDraft(current, draft) : current);
    }).catch((err: Error) => setError(err.message));
  }, [blockId, from]);
  if (error) return <ErrorBox text={error} />;
  if (!file || !start) return <Loading />;
  return <>
    <nav className="breadcrumb"><Link to="/blocks">{t("Blocks")}</Link><ChevronRight size={12} /><Link to={`/blocks/${encodeURIComponent(blockId)}`}>{file.name}</Link><ChevronRight size={12} /><span>{t("New version")}</span></nav>
    {/* The page's top is its title (ui 0.41.0): the version it makes is on the save button. */}
    <Heading title={t("New version of {name}", { name: file.name })}
      detail={t("Filled in from version {number}. Change what you need, test it on an asset, and save it as version {next}. The algorithms that use this block keep the version they name until they are updated.", { number: start.number, next: start.next })} />
    <Workbench start={file} me={me} existing={{ blockId, file, next: start.next }} onCancel={() => navigate(`/blocks/${encodeURIComponent(blockId)}${from ? `?version=${from}` : ""}`)} />
  </>;
}
