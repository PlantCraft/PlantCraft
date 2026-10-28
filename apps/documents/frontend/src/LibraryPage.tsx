/** The library: folders, the documents of the one chosen (or of one asset), sending files. */
import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import { DataTable, Dialog, FolderButton, Pill, confirmAction, useAssistantPage } from "@plantcraft/ui";
import { FolderPlus, Upload } from "lucide-react";
import { api, type FolderDraft } from "./api";
import { formatAgo, t } from "./i18n";
import { navigate } from "./nav";
import { ACCEPT, SendDialog, fileTypesLine } from "./send";
import type { DocRow, Folder, Me } from "./types";
import { ErrorBox, Heading, Link, Loading, message } from "./ui";

export const STATUS_WORDS: Record<string, string> = {
  queued: "Waiting to be read", indexing: "Reading", indexed: "Read", failed: "Could not be read", superseded: "Superseded",
};
export const STATUS_PILL: Record<string, string> = { queued: "queued", indexing: "running", indexed: "good", failed: "failed", superseded: "inactive" };

export function StatusPill({ status }: { status: string | null }) {
  if (!status) return <>–</>;
  return <Pill status={STATUS_PILL[status] ?? "unknown"} label={t(STATUS_WORDS[status] ?? status)} />;
}

const lines = (text: string) => text.split(/[\s,]+/).map((item) => item.trim()).filter(Boolean);

function FolderDialog({ folder, onClose, onSaved }: { folder: Folder | null; onClose: () => void; onSaved: (folder: Folder) => void }) {
  const [name, setName] = useState(folder?.name ?? "");
  const [description, setDescription] = useState(folder?.description ?? "");
  const [viewers, setViewers] = useState((folder?.viewers ?? []).join("\n"));
  const [editors, setEditors] = useState((folder?.editors ?? []).join("\n"));
  const [assistant, setAssistant] = useState(folder?.assistant ?? true);
  const [error, setError] = useState("");
  const save = () => {
    const draft: FolderDraft = { name: name.trim(), description: description.trim(), viewers: lines(viewers), editors: lines(editors), assistant };
    (folder ? api.saveFolder(folder.folder_id, draft) : api.createFolder(draft)).then((saved) => { onSaved(saved); onClose(); }).catch((err) => setError(message(err)));
  };
  return <Dialog title={folder ? t("Folder {name}", { name: folder.name }) : t("New folder")} onClose={onClose}
    onSubmit={(event) => { event.preventDefault(); save(); }}
    footer={<><button className="button button-secondary" type="button" onClick={onClose}>{t("Cancel")}</button>
      <button className="button button-primary" type="submit">{t("Save")}</button></>}>
    <div className="form-grid">
      <label>{t("Name")}<input value={name} onChange={(event) => setName(event.target.value)} maxLength={80} required /></label>
      <label>{t("Description")}<input value={description} onChange={(event) => setDescription(event.target.value)} maxLength={300} /></label>
      <label>{t("Who sees it")}<textarea rows={3} value={viewers} onChange={(event) => setViewers(event.target.value)} placeholder={"user:ana\ngroup:operations"} /></label>
      <label>{t("Who changes it")}<textarea rows={3} value={editors} onChange={(event) => setEditors(event.target.value)} placeholder="group:process-engineering" /></label>
    </div>
    <p className="muted">{t("One per line: user:<username> or group:<group id>. Empty means everyone with access to Documents (editors change).")}</p>
    <label className="check"><input type="checkbox" checked={assistant} onChange={(event) => setAssistant(event.target.checked)} /> {t("The assistant may read its documents")}</label>
    {error && <ErrorBox text={error} />}
  </Dialog>;
}

/** `/folders/general`: the documents in no folder (General, everyone's). */
export const GENERAL = "general";

/** The library's folders in the left column, as every list of the suite shows its folders
 * (`pc-folder-layout`, Analytics' algorithms, Models' studies): All, each folder with its count,
 * General, and New folder for editors. Documents' folders also say who reads them, so they keep
 * their own dialog; a folder not for the assistant is marked. */
function FolderList({ folders, docs, chosen, canEdit, onNew }: { folders: Folder[]; docs: DocRow[]; chosen: string; canEdit: boolean; onNew: () => void }) {
  const count = (folderId: string) => docs.filter((doc) => doc.folder_id === folderId).length;
  const go = (folderId: string) => navigate(folderId ? `/folders/${folderId}` : "/documents");
  return <nav className="panel pc-folders" aria-label={t("Folders")}>
    <FolderButton active={!chosen} onClick={() => go("")} count={docs.length}>{t("All")}</FolderButton>
    <h2 className="pc-folder-heading">{t("Folders")}</h2>
    {folders.map((item) => <FolderButton key={item.folder_id} active={chosen === item.folder_id} onClick={() => go(item.folder_id)} count={count(item.folder_id)}>
      {item.name}{!item.assistant && <span className="folder-mark" title={t("Not for the assistant")} aria-label={t("Not for the assistant")}> ⊘</span>}
    </FolderButton>)}
    <FolderButton active={chosen === GENERAL} onClick={() => go(GENERAL)} count={count("")}><i>{t("General")}</i></FolderButton>
    {canEdit && <button type="button" className="pc-folder-new" onClick={onNew}><FolderPlus size={15} />{t("New folder")}</button>}
  </nav>;
}

/** `/documents`, `/folders/<id>` and `/assets/<id>`: the documents, sending files and the folders. */
export function LibraryPage({ me, folderId, assetId }: { me: Me; folderId?: string; assetId?: string }) {
  const [docs, setDocs] = useState<DocRow[] | null>(null);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [kinds, setKinds] = useState<string[]>([]);
  const [files, setFiles] = useState<File[] | null>(null);
  const [editing, setEditing] = useState<Folder | null | undefined>(undefined);
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  const general = folderId === GENERAL;
  const folder = folders.find((item) => item.folder_id === folderId);
  // Every document the person sees, once: the folders' counts and the folder shown come from it.
  const load = useCallback(() => Promise.all([
    api.documents({ asset: assetId }), api.folders(), api.kinds(),
  ]).then(([list, folderList, kindList]) => { setDocs(list); setFolders(folderList); setKinds(kindList); }).catch((err) => setError(message(err))), [assetId]);
  useEffect(() => { void load(); }, [load]);
  // While files are read, look again every few seconds.
  const reading = docs?.some((doc) => doc.status === "queued" || doc.status === "indexing");
  useEffect(() => {
    if (!reading) return;
    const timer = window.setInterval(() => void load(), 4000);
    return () => window.clearInterval(timer);
  }, [reading, load]);
  const shown = !docs ? null : assetId || !folderId ? docs : docs.filter((doc) => doc.folder_id === (general ? "" : folderId));
  const canSend = me.can_edit && (!folder || folder.can_edit);
  useAssistantPage(shown && (assetId
    ? { page: "doccraft:asset", subject: `asset:${assetId}`, title: assetId, place: t("Documents › Asset {id}", { id: assetId }), platformUrl: me.processcraft_url,
        facts: { asset: assetId, documents: shown.length }, view: { documents: shown.slice(0, 30).map((doc) => doc.number || doc.doc_id) } }
    : { page: "doccraft:documents", place: folder ? t("Documents › {folder}", { folder: folder.name }) : t("Documents"), platformUrl: me.processcraft_url,
        facts: { documents: shown.length, folder: folder?.name ?? (general ? t("General") : t("All")), embedder: me.embedder } }));

  if (error) return <ErrorBox text={error} />;
  if (!docs || !shown) return <Loading />;
  const drop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    if (canSend && event.dataTransfer.files.length) setFiles([...event.dataTransfer.files]);
  };
  const removeFolder = async (item: Folder) => {
    if (!(await confirmAction(t("Only an empty folder is deleted."), { title: t("Delete folder {name}?", { name: item.name }), confirm: t("Delete"), danger: true }))) return;
    api.removeFolder(item.folder_id).then(() => { navigate("/documents"); void load(); }).catch((err) => setError(message(err)));
  };
  const table = !shown.length
    ? <div className="panel empty"><h2>{t("No documents here yet")}</h2><p className="muted">{canSend ? t("Send files, or drop them on this page.") : t("An editor sends the first ones.")}</p>
      {canSend && <p className="muted small">{fileTypesLine(me.max_file_mb)}</p>}</div>
    : <DataTable rows={shown} rowKey={(doc) => doc.doc_id} label={t("Documents")}
      searchText={(doc) => `${doc.number} ${doc.title} ${doc.description} ${doc.kind} ${doc.unit} ${doc.assets.map((item) => item.asset_id).join(" ")}`}
      searchPlaceholder={t("Search number, title, description, unit or asset")}
      onRowClick={(doc) => navigate(`/documents/${doc.doc_id}`)}
      initialSort={{ key: "number", descending: false }}
      columns={[
        { key: "number", label: t("Number"), className: "nowrap", sort: (doc) => doc.number, render: (doc) => <Link to={`/documents/${doc.doc_id}`}>{doc.number || "–"}</Link> },
        { key: "title", label: t("Title"), sort: (doc) => doc.title, render: (doc) => <><Link to={`/documents/${doc.doc_id}`} className="strong">{doc.title}</Link>{doc.description && <small className="doc-description">{doc.description}</small>}</> },
        { key: "kind", label: t("Kind"), sort: (doc) => doc.kind, filter: true, render: (doc) => t(doc.kind) },
        { key: "unit", label: t("Unit"), sort: (doc) => doc.unit, filter: true, render: (doc) => doc.unit || "–" },
        { key: "revision", label: t("Rev."), className: "nowrap", sort: (doc) => doc.revision ?? "", render: (doc) => doc.revision || "–" },
        { key: "status", label: t("Reading"), sort: (doc) => doc.status ?? "", filter: true, render: (doc) => <StatusPill status={doc.status} /> },
        { key: "assets", label: t("Assets"), sort: (doc) => doc.assets.length, render: (doc) => doc.assets.filter((item) => item.source === "manual").map((item) => item.asset_id).slice(0, 4).join(", ") || <span className="muted">{t("{n} suggested", { n: doc.assets.length })}</span> },
        { key: "when", label: t("Sent"), sort: (doc) => doc.uploaded_at ?? "", render: (doc) => (doc.uploaded_at ? formatAgo(doc.uploaded_at) : "–") },
      ]} />;
  return <div onDragOver={(event) => { if (canSend) { event.preventDefault(); setDragging(true); } }} onDragLeave={() => setDragging(false)} onDrop={drop}
    className={dragging ? "drop-target dragging" : "drop-target"}>
    <Heading title={assetId ? t("Documents about {id}", { id: assetId }) : folder ? folder.name : general ? t("General") : t("Documents")} actions={<>
      {canSend && !assetId && <button className="button button-primary" type="button" onClick={() => picker.current?.click()} title={fileTypesLine(me.max_file_mb)}><Upload size={16} /> {t("Send files")}</button>}
    </>} />
    <input ref={picker} type="file" multiple accept={ACCEPT} hidden onChange={(event) => { if (event.target.files?.length) setFiles([...event.target.files]); event.target.value = ""; }} />
    {canSend && !assetId && <p className="muted send-types"><Upload size={14} aria-hidden="true" /> {fileTypesLine(me.max_file_mb)} {t("Drop them anywhere on this page.")}</p>}
    {assetId
      ? <>
        <p className="muted">{t("Documents linked to this asset by a person. The search also finds passages that only name it.")} <Link to={`/search?asset=${encodeURIComponent(assetId)}`}>{t("Search its passages")}</Link></p>
        {table}
      </>
      : <div className="pc-folder-layout">
        <FolderList folders={folders} docs={docs} chosen={folderId ?? ""} canEdit={me.can_edit} onNew={() => setEditing(null)} />
        <section>
          {folder && <p className="muted folder-line">{folder.description} {folder.viewers.length ? t("Seen by {who}.", { who: folder.viewers.join(", ") }) : t("Seen by everyone.")}{" "}
            {!folder.assistant && <>{t("The assistant does not read its documents.")} </>}
            {folder.can_edit && <><button className="link-button" type="button" onClick={() => setEditing(folder)}>{t("Change")}</button> · <button className="link-button" type="button" onClick={() => void removeFolder(folder)}>{t("Delete")}</button></>}</p>}
          {general && <p className="muted folder-line">{t("The documents in no folder: everyone with access to Documents sees them.")}</p>}
          {table}
        </section>
      </div>}
    {files && <SendDialog files={files} folders={folders} kinds={kinds} folder={folder?.can_edit ? folder.folder_id : ""} onClose={() => setFiles(null)} onSent={() => void load()} />}
    {editing !== undefined && <FolderDialog folder={editing} onClose={() => setEditing(undefined)} onSaved={(saved) => { void load(); navigate(`/folders/${saved.folder_id}`); }} />}
  </div>;
}
