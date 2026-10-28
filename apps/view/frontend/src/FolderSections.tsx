/** The folders of a list page, the same for dashboards and reports: one band per folder (its
 * count, who sees and edits it, its actions), General last, and the folder dialogs. */
import { confirmAction, errorMessage as message } from "@plantcraft/ui";
import { Eye, Folder as FolderIcon, Info, Pencil, Plus, Trash2 } from "lucide-react";
import { useState, type ReactNode } from "react";
import { api } from "./api";
import { FolderDialog } from "./FolderDialogs";
import { t } from "./i18n";
import { accessLabel } from "./model";
import type { Folder, Me } from "./types";

/** What the bands say about their items, in the page's own words. */
export interface FolderWords {
  /** "Dashboards in this folder" */
  count: string;
  /** "Who sees these dashboards" */
  sees: string;
  /** "Who edits these dashboards" */
  edits: string;
  /** "New dashboard here" */
  newHere: string;
  /** "New dashboard in {name}" */
  newIn: string;
  /** "No dashboard in this folder yet." */
  empty: string;
}

export function FolderSections<T>({ me, folders, items, folderOf, render, words, search, onNew, onChanged, onError }: {
  me: Me; folders: Folder[]; items: T[]; folderOf: (item: T) => string; render: (item: T) => ReactNode;
  words: FolderWords; search: string; onNew: (folderId: string) => void; onChanged: () => void; onError: (text: string) => void;
}) {
  const [dialog, setDialog] = useState<Folder | null>(null);
  const known = new Set(folders.map((folder) => folder.folder_id));
  const sections: Array<{ folder: Folder | null; items: T[] }> = [
    ...folders.map((folder) => ({ folder, items: items.filter((item) => folderOf(item) === folder.folder_id) })),
    { folder: null, items: items.filter((item) => !folderOf(item) || !known.has(folderOf(item))) },
  ].filter((section) => section.items.length || (!search && section.folder));

  async function remove(folder: Folder) {
    if (!await confirmAction(t("Delete the folder \"{name}\"?", { name: folder.name }), { confirm: t("Delete"), danger: true })) return;
    try { await api.removeFolder(folder.folder_id); onChanged(); } catch (err) { onError(message(err)); }
  }

  return <>
    {sections.map(({ folder, items: inside }) => <details key={folder?.folder_id ?? "general"} className="tc-folder" open>
      <summary>
        <FolderIcon size={16} aria-hidden />
        <h2>{folder ? folder.name : t("General")}</h2>
        <span className="tc-folder-count pc-num" title={words.count}>{inside.length}</span>
        <span className="tag" title={words.sees}><Eye size={11} /> {folder ? accessLabel(folder.viewers) : t("Everyone")}</span>
        {folder && folder.editors.length > 0 && <span className="tag" title={words.edits}><Pencil size={11} /> {accessLabel(folder.editors)}</span>}
        <small className="muted">{folder?.description || (folder ? "" : t("Outside any folder: everyone with access to View sees it."))}</small>
      </summary>
      <span className="tc-folder-actions">
        {me.can_edit && (!folder || folder.can_edit) && <button type="button" className="icon-button" title={words.newHere} aria-label={t(words.newIn, { name: folder?.name ?? t("General") })} onClick={(event) => { event.preventDefault(); onNew(folder?.folder_id ?? ""); }}><Plus size={15} /></button>}
        {folder?.can_edit && <button type="button" className="icon-button" title={t("Folder settings")} aria-label={t("Settings of {name}", { name: folder.name })} onClick={(event) => { event.preventDefault(); setDialog(folder); }}><Pencil size={15} /></button>}
        {!folder && me.can_edit && <span className="icon-button tc-folder-info" tabIndex={0} role="img" title={t("General is not a folder: it holds what is outside every folder, open to everyone, so it has no settings. Make a folder to choose who sees and edits.")} aria-label={t("About General")}><Info size={15} /></span>}
        {folder?.can_edit && !folder.dashboards && !folder.reports && <button type="button" className="icon-button" title={t("Delete folder")} aria-label={t("Delete folder {name}", { name: folder.name })} onClick={(event) => { event.preventDefault(); void remove(folder); }}><Trash2 size={15} /></button>}
      </span>
      {inside.length ? <section className="pc-grid">{inside.map(render)}</section> : <p className="muted tc-folder-empty">{words.empty}</p>}
    </details>)}
    {dialog && <FolderDialog folder={dialog} onClose={() => setDialog(null)} onSaved={() => { setDialog(null); onChanged(); }} />}
  </>;
}
