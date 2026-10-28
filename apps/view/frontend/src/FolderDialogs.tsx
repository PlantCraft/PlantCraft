/** The dialogs of the dashboards list: a new dashboard (name, folder, what it starts from) and a
 * folder (name, who sees and who edits its dashboards). */
import { Dialog, RecipientPicker, errorMessage as message } from "@plantcraft/ui";
import { FileUp } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { api } from "./api";
import { t } from "./i18n";
import { draftOf, EMPTY_DRAFT, importDashboard } from "./model";
import type { DashboardDraft, Directory, Folder, FolderDraft, Template } from "./types";
import { ErrorBox } from "./ui";

const NEW_DRAFT_KEY = "dashcraft.new-dashboard";
let pending: DashboardDraft | null = null;

/** The dashboard the New dashboard dialog starts: kept until the editor saves or leaves it. */
export function holdNewDraft(draft: DashboardDraft) {
  pending = draft;
  try { sessionStorage.setItem(NEW_DRAFT_KEY, JSON.stringify(draft)); } catch { /* the module copy is enough */ }
}
export function takeNewDraft(): DashboardDraft | null {
  if (pending) return pending;
  try {
    const text = sessionStorage.getItem(NEW_DRAFT_KEY);
    return text ? draftOf(JSON.parse(text) as DashboardDraft) : null;
  } catch { return null; }
}
export function dropNewDraft() {
  pending = null;
  try { sessionStorage.removeItem(NEW_DRAFT_KEY); } catch { /* nothing kept */ }
}

/** The folders a person may add dashboards and reports to: General ("") and those they edit. */
export function FolderSelect({ folders, value, onChange, canGeneral = true }: { folders: Folder[]; value: string; onChange: (folderId: string) => void; canGeneral?: boolean }) {
  const editable = folders.filter((folder) => folder.can_edit || folder.folder_id === value);
  return <select value={value} onChange={(event) => onChange(event.target.value)}>
    {canGeneral && <option value="">{t("General")}</option>}
    {editable.map((folder) => <option key={folder.folder_id} value={folder.folder_id}>{folder.name}</option>)}
  </select>;
}

export function NewDashboardDialog({ folders, folderId, onStart, onClose }: { folders: Folder[]; folderId: string; onStart: (draft: DashboardDraft) => void; onClose: () => void }) {
  const [name, setName] = useState("");
  const [folder, setFolder] = useState(folderId);
  const [start, setStart] = useState("empty");
  const [templates, setTemplates] = useState<Template[] | null>(null);
  const [file, setFile] = useState<DashboardDraft | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.templates().then(setTemplates).catch(() => setTemplates([])); }, []);

  async function pick(chosen: File | undefined) {
    if (!chosen) return;
    try {
      const draft = importDashboard(await chosen.text());
      setFile(draft);
      setStart("file");
      if (!name.trim()) setName(draft.name);
      setError("");
    } catch (err) { setError(message(err)); }
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    const template = templates?.find((item) => item.template_id === start);
    const base = start === "file" && file ? file : template ? draftOf({ ...template.draft, name: template.name }) : EMPTY_DRAFT;
    onStart({ ...base, name: name.trim() || base.name, folder_id: folder });
  }
  return <Dialog title={t("New dashboard")} onClose={onClose} onSubmit={submit}>
      {error && <ErrorBox text={error} />}
      <div className="form-grid tc-settings">
        <label>{t("Name")}<input autoFocus maxLength={120} value={name} placeholder={t("Unit 100 shift view")} onChange={(event) => setName(event.target.value)} /></label>
        <label>{t("Folder")}<FolderSelect folders={folders} value={folder} onChange={setFolder} /></label>
        <fieldset className="tc-wide tc-start">
          <legend>{t("Start from")}</legend>
          <label className="tc-choice"><input type="radio" name="start" checked={start === "empty"} onChange={() => setStart("empty")} /><span><b>{t("An empty grid")}</b><small>{t("Add the panels yourself.")}</small></span></label>
          {(templates ?? []).map((item) => <label key={item.template_id} className="tc-choice"><input type="radio" name="start" checked={start === item.template_id} onChange={() => setStart(item.template_id)} /><span><b>{item.name}</b><small>{item.description} · {t("{count} panels", { count: item.cards })}</small></span></label>)}
          {templates === null && <small className="muted">{t("Reading the plant's assets…")}</small>}
          <label className="tc-choice"><input type="radio" name="start" checked={start === "file"} disabled={!file} onChange={() => setStart("file")} /><span><b>{file ? t("The file {name}", { name: file.name }) : t("A dashboard file")}</b><small>{t("Exported from View, here or in another installation (Config › JSON).")}</small></span></label>
          <label className="button button-secondary button-small tc-file"><FileUp size={14} /> {t("Choose a file…")}<input type="file" accept="application/json,.json" className="sr-only" onChange={(event) => void pick(event.target.files?.[0])} /></label>
        </fieldset>
      </div>
      <footer><button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button><button className="button button-primary" type="submit">{t("Open the editor")}</button></footer>
      <p className="muted tc-dialog-note">{t("Nothing is saved until you press Save in the editor.")}</p>
  </Dialog>;
}

function Audience({ label, hint, everyone, value, onChange, directory }: { label: string; hint: string; everyone: string; value: string[]; onChange: (value: string[]) => void; directory: Directory | null }) {
  const [only, setOnly] = useState(value.length > 0);
  return <fieldset className="tc-wide tc-audience">
    <legend>{label}</legend>
    <label className="tc-choice"><input type="radio" checked={!only} onChange={() => { setOnly(false); onChange([]); }} /><span><b>{everyone}</b></span></label>
    <label className="tc-choice"><input type="radio" checked={only} onChange={() => setOnly(true)} /><span><b>{t("Only these people and groups")}</b><small>{hint}</small></span></label>
    {only && <RecipientPicker label={label} value={value} onChange={onChange} people={directory?.people ?? []} groups={directory?.groups ?? []} placeholder={t("A person or a group of the platform…")} />}
  </fieldset>;
}

export function FolderDialog({ folder, onSaved, onClose }: { folder: Folder | null; onSaved: (folder: Folder) => void; onClose: () => void }) {
  const [value, setValue] = useState<FolderDraft>(() => ({ name: folder?.name ?? "", description: folder?.description ?? "", viewers: folder?.viewers ?? [], editors: folder?.editors ?? [] }));
  const [directory, setDirectory] = useState<Directory | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => { api.directory().then(setDirectory).catch((err) => setError(message(err))); }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    try { onSaved(folder ? await api.saveFolder(folder.folder_id, value) : await api.createFolder(value)); } catch (err) { setError(message(err)); } finally { setSaving(false); }
  }
  return <Dialog title={folder ? t("Folder {name}", { name: folder.name }) : t("New folder")} onClose={onClose} onSubmit={(event) => void submit(event)}>
      {error && <ErrorBox text={error} />}
      <div className="form-grid tc-settings">
        <label>{t("Name")}<input required autoFocus maxLength={80} value={value.name} onChange={(event) => setValue({ ...value, name: event.target.value })} /></label>
        <label>{t("Description")}<input maxLength={300} value={value.description} onChange={(event) => setValue({ ...value, description: event.target.value })} /></label>
        <Audience label={t("Who sees its dashboards and reports")} everyone={t("Everyone with access to View")} hint={t("Others do not see the folder or what it holds anywhere. Administrators always do.")}
          value={value.viewers} onChange={(viewers) => setValue({ ...value, viewers })} directory={directory} />
        <Audience label={t("Who edits its dashboards and reports")} everyone={t("Every editor of View")} hint={t("Only View editors among them change, add, share or delete what it holds; they always see it.")}
          value={value.editors} onChange={(editors) => setValue({ ...value, editors })} directory={directory} />
      </div>
      <footer><button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button><button className="button button-primary" type="submit" disabled={saving}>{saving ? t("Saving…") : t("Save")}</button></footer>
  </Dialog>;
}
