/**
 * Folders for an app's own objects (Link round 9 D14; Models round 9 M5): one interface for the
 * suite, over the SDK's `folders_router` (`/api/folders/<kind>`). A list page shows its folders in
 * a column on the left (`?folder=`); an object is put in one when it is made and moved only with
 * Move to folder, which records who moved it, so nothing wanders between folders.
 *
 * The app sets it up once with `configureFolders({ request, href, listPath })`: its API client's
 * `request`, its `href`, and the list page of each kind (where a folder's name links to).
 */
import { FolderInput, FolderPlus } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { errorMessage, jsonBody } from "./api.js";
import { Dialog } from "./Dialog.js";
import { formatDate } from "./format.js";
import { t } from "./i18n.js";

export type Folder = { folder_id: string; kind: string; name: string; count: number; created_by: string; created_at: string };
export type FolderPlace = { item_id: string; folder_id: string; moved_by: string; moved_at: string };
export type FolderList = { folders: Folder[]; items: Record<string, FolderPlace> };

export interface FoldersConfig {
  /** The app's API client (`createApiClient(...).request`). */
  request: <T>(path: string, init?: RequestInit) => Promise<T>;
  /** The browser path of an app path (`createNav(...).href`). */
  href: (path: string) => string;
  /** The list page of a kind, e.g. `study` -> `/studies`. */
  listPath: (kind: string) => string;
}

let config: FoldersConfig | null = null;

export function configureFolders(options: FoldersConfig) {
  config = options;
}

function setup(): FoldersConfig {
  if (!config) throw new Error("configureFolders() was not called");
  return config;
}

const enc = encodeURIComponent;

/** The folders API of the app (`/api/folders`). */
export const folderApi = {
  list: (kind: string) => setup().request<FolderList>(`/api/folders/${enc(kind)}`),
  create: (kind: string, name: string) => setup().request<Folder>(`/api/folders/${enc(kind)}`, jsonBody("POST", { name })),
  rename: (kind: string, folderId: string, name: string) => setup().request<Folder>(`/api/folders/${enc(kind)}/${enc(folderId)}`, jsonBody("PATCH", { name })),
  remove: (kind: string, folderId: string) => setup().request<void>(`/api/folders/${enc(kind)}/${enc(folderId)}`, { method: "DELETE" }),
  move: (kind: string, itemId: string, folderId: string) =>
    setup().request<{ place: FolderPlace | null }>(`/api/folders/${enc(kind)}/items/${enc(itemId)}`, jsonBody("PUT", { folder_id: folderId })),
};

/** `?folder=` of a list: a folder id, "none" (in no folder) or "" (all). */
export const NO_FOLDER = "none";

export function chosenFolder(search: string): string {
  return new URLSearchParams(search).get("folder") ?? "";
}

/** Whether an object shows under the chosen folder. */
export function inFolder(list: FolderList | null, itemId: string, chosen: string): boolean {
  if (!chosen) return true;
  const place = list?.items[itemId]?.folder_id ?? "";
  return chosen === NO_FOLDER ? !place : place === chosen;
}

/** The path of a list page with its `?folder=` (none when "" is chosen). */
export function folderPath(path: string, folder: string): string {
  return folder ? `${path}?folder=${enc(folder)}` : path;
}

/** The page that makes a new object, in the chosen folder (`/studies/new?folder=f1`). */
export function newInFolder(path: string, folder: string): string {
  return folderPath(path, folder === NO_FOLDER ? "" : folder);
}

/** Keep a list's `?folder=` in the address without a new history entry. */
export function rememberFolder(path: string, folder: string) {
  window.history.replaceState({}, "", setup().href(folderPath(path, folder)));
}

/** The kind's folders, reloaded after a change. */
export function useFolders(kind: string): [FolderList | null, () => void] {
  const [list, setList] = useState<FolderList | null>(null);
  const [loaded, setLoaded] = useState(0);
  useEffect(() => { folderApi.list(kind).then(setList).catch(() => setList({ folders: [], items: {} })); }, [kind, loaded]);
  return [list, () => setLoaded((now) => now + 1)];
}

/** After an object is made: put it in the folder its form chose (nothing when none). */
export async function putInFolder(kind: string, itemId: string, folder: string): Promise<void> {
  if (folder && folder !== NO_FOLDER) await folderApi.move(kind, itemId, folder);
}

/** One entry of a folder column (also an app's own entries above the folders: Link's libraries). */
export function FolderButton({ active, onClick, children, count }: { active: boolean; onClick: () => void; children: ReactNode; count?: number | null }) {
  return <button type="button" className={`pc-folder${active ? " active" : ""}`} aria-current={active ? "true" : undefined} onClick={onClick}>
    <span>{children}</span>{count !== null && count !== undefined && <small className="pc-num">{count}</small>}
  </button>;
}

function NewFolderDialog({ kind, onClose, onMade }: { kind: string; onClose: () => void; onMade: (folderId: string) => void }) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function make() {
    setBusy(true); setError("");
    try { onMade((await folderApi.create(kind, name.trim())).folder_id); } catch (err) { setError(errorMessage(err)); setBusy(false); }
  }
  return <Dialog title={t("New folder")} onClose={onClose} initialFocus="#pc-folder-name" onSubmit={(event) => { event.preventDefault(); if (name.trim()) void make(); }}
    footer={<><button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button><button type="submit" className="button button-primary" disabled={busy || !name.trim()}>{t("Make the folder")}</button></>}>
    <label className="pc-field">{t("Name")}<input id="pc-folder-name" value={name} maxLength={80} onChange={(event) => setName(event.target.value)} /></label>
    {error && <p className="pc-folder-error" role="alert">{error}</p>}
  </Dialog>;
}

/**
 * A list's libraries in its left column (inside a `pc-folder-layout`), in place of folders where
 * the objects belong to a library (Link's blocks, round 10): the "Libraries" heading, each library
 * with its count, and `footer` under them (New library).
 */
export function LibraryColumn({ libraries, chosen, onChoose, label, footer }: {
  libraries: Array<{ library: string; name: string; count?: number | null }>; chosen: string; onChoose: (library: string) => void;
  label?: string; footer?: ReactNode;
}) {
  return <nav className="panel pc-folders pc-libraries" aria-label={label ?? t("Libraries")}>
    <h2 className="pc-folder-heading">{t("Libraries")}</h2>
    {libraries.map((item) => <FolderButton key={item.library} active={chosen === item.library} onClick={() => onChoose(item.library)} count={item.count ?? null}>{item.name}</FolderButton>)}
    {footer}
  </nav>;
}

/**
 * The folders of a list, in its left column (inside a `pc-folder-layout`): All, each folder with
 * its count, In no folder, and New folder for editors. `before` goes above them in place of All
 * (Link's block libraries, as `FolderButton`s).
 */
export function FolderColumn({ kind, list, chosen, onChoose, total, canEdit, onChanged, before, label }: {
  kind: string; list: FolderList | null; chosen: string; onChoose: (folder: string) => void; total: number;
  canEdit: boolean; onChanged: () => void; before?: ReactNode; label?: string;
}) {
  const [making, setMaking] = useState(false);
  const placed = Object.keys(list?.items ?? {}).length;
  const entry = (value: string, name: ReactNode, count: number | null) =>
    <FolderButton key={value || "all"} active={chosen === value} onClick={() => onChoose(value)} count={count}>{name}</FolderButton>;
  return <><nav className="panel pc-folders" aria-label={label ?? t("Folders")}>
    {before}
    {!before && entry("", t("All"), total)}
    <h2 className="pc-folder-heading">{t("Folders")}</h2>
    {(list?.folders ?? []).map((folder) => entry(folder.folder_id, folder.name, folder.count))}
    {entry(NO_FOLDER, <i>{t("In no folder")}</i>, before ? null : Math.max(0, total - placed))}
    {canEdit && <button type="button" className="pc-folder-new" onClick={() => setMaking(true)}><FolderPlus size={15} />{t("New folder")}</button>}
  </nav>
  {making && <NewFolderDialog kind={kind} onClose={() => setMaking(false)} onMade={(folderId) => { setMaking(false); onChanged(); onChoose(folderId); }} />}
  </>;
}

/** The heading of a list showing one folder (or In no folder); nothing when All is chosen. */
export function folderName(list: FolderList | null, chosen: string): string {
  if (!chosen) return "";
  if (chosen === NO_FOLDER) return t("In no folder");
  return list?.folders.find((item) => item.folder_id === chosen)?.name ?? "";
}

/** The field of a form that makes an object: the folder it goes in (`?folder=` of the list). */
export function FolderField({ kind, value, onChange }: { kind: string; value: string; onChange: (folder: string) => void }) {
  const [list] = useFolders(kind);
  if (!list?.folders.length) return null;
  return <label className="pc-field pc-folder-field">{t("Folder")}
    <select id={`${kind}-folder`} value={value === NO_FOLDER ? "" : value} onChange={(event) => onChange(event.target.value)}>
      <option value="">{t("In no folder")}</option>
      {list.folders.map((folder) => <option key={folder.folder_id} value={folder.folder_id}>{folder.name}</option>)}
    </select>
  </label>;
}

/** The folder an object is in, on its page, with Move to folder for editors (who moved it, when). */
export function FolderPlaceLine({ kind, itemId, canEdit }: { kind: string; itemId: string; canEdit: boolean }) {
  const [list, reload] = useFolders(kind);
  const [moving, setMoving] = useState(false);
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!list) return null;
  const place = list.items[itemId];
  const folder = list.folders.find((item) => item.folder_id === place?.folder_id);
  if (!folder && !canEdit) return null;
  async function move() {
    setBusy(true); setError("");
    try { await folderApi.move(kind, itemId, target); setMoving(false); reload(); } catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  }
  const { href, listPath } = setup();
  return <div className="pc-folder-place">
    <FolderInput size={14} aria-hidden="true" />
    <span>{folder ? <>{t("In the folder")} <a href={href(folderPath(listPath(kind), folder.folder_id))}><b>{folder.name}</b></a>{place?.moved_by ? <small className="muted"> · {t("moved by {who} on {when}", { who: place.moved_by, when: formatDate(place.moved_at) })}</small> : null}</> : <span className="muted">{t("In no folder")}</span>}</span>
    {canEdit && <button type="button" className="link-button" onClick={() => { setTarget(place?.folder_id ?? ""); setMoving(true); }}>{t("Move to folder")}</button>}
    {/* No form of its own: the line can sit inside an object's form. */}
    {moving && <Dialog title={t("Move to folder")} onClose={() => setMoving(false)} initialFocus="#pc-folder-target"
      footer={<><button type="button" className="button button-secondary" onClick={() => setMoving(false)}>{t("Cancel")}</button><button type="button" className="button button-primary" disabled={busy || target === (place?.folder_id ?? "")} onClick={() => void move()}>{t("Move")}</button></>}>
      <label className="pc-field">{t("Folder")}
        <select id="pc-folder-target" value={target} onChange={(event) => setTarget(event.target.value)}>
          <option value="">{t("In no folder")}</option>
          {list.folders.map((item) => <option key={item.folder_id} value={item.folder_id}>{item.name}</option>)}
        </select>
      </label>
      {!list.folders.length && <p className="muted">{t("There is no folder yet: make one with New folder on the list.")}</p>}
      {error && <p className="pc-folder-error" role="alert">{error}</p>}
    </Dialog>}
  </div>;
}
