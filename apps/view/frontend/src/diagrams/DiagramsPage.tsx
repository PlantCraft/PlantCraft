/** View › Diagrams: the plant's process graphics, by folder; open one, draw a new one. */
import { confirmAction, errorMessage as message, useAssistantPage } from "@plantcraft/ui";
import { ChevronRight, Plus, Search, Trash2, Workflow } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { t } from "../i18n";
import { when } from "../model";
import { navigate } from "../nav";
import type { Folder, Me } from "../types";
import { ErrorBox, Heading, Link, Loading } from "../ui";
import { diagramsApi } from "./api";
import type { DiagramSummary } from "./model";
import "./diagrams.css";

function matches(item: DiagramSummary, search: string): boolean {
  const words = search.trim().toLowerCase();
  if (!words) return true;
  return [item.name, item.description, ...(item.tags ?? [])].some((text) => (text ?? "").toLowerCase().includes(words));
}

export function DiagramsPage({ me }: { me: Me }) {
  const [items, setItems] = useState<DiagramSummary[] | null>(null);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const load = useCallback(() => Promise.all([diagramsApi.list(), api.folders()]).then(([found, kept]) => { setItems(found); setFolders(kept); }).catch((err) => setError(message(err))), []);
  useEffect(() => { void load(); }, [load]);
  useAssistantPage({ place: t("View › Process"), page: "dashcraft:diagrams", facts: { diagrams: items?.length ?? 0 },
    view: { diagrams: (items ?? []).slice(0, 40).map((item) => `${item.name.slice(0, 80)}${item.description ? `: ${item.description.slice(0, 100)}` : ""}`) } });

  async function remove(item: DiagramSummary) {
    if (!await confirmAction(t("Delete the process display \"{name}\"?", { name: item.name }), { confirm: t("Delete"), danger: true })) return;
    try { await diagramsApi.remove(item.diagram_id); await load(); } catch (err) { setError(message(err)); }
  }
  const shown = (items ?? []).filter((item) => matches(item, search));
  const folderName = (folderId: string) => folders.find((folder) => folder.folder_id === folderId)?.name ?? t("General");
  const groups = new Map<string, DiagramSummary[]>();
  for (const item of shown) groups.set(item.folder_id || "", [...(groups.get(item.folder_id || "") ?? []), item]);

  return <>
    <Heading eyebrow={t("View")} title={t("Process")}
      detail={t("Process graphics of the plant: equipment joined by its lines, with live values and colours, and a time bar to play back what happened.")}
      actions={me.can_edit && <button className="button button-primary" onClick={() => navigate("/diagrams/new")}><Plus size={16} /> {t("New process display")}</button>} />
    {error && <ErrorBox text={error} />}
    {!items && !error && <Loading />}
    {items && items.length > 0 && <label className="tc-find"><Search size={15} aria-hidden /><input type="search" aria-label={t("Find a process display")} placeholder={t("Find by name, description or tag")} value={search} onChange={(event) => setSearch(event.target.value)} /></label>}
    {items && items.length === 0 && <div className="panel tc-empty-list">
      <Workflow size={28} aria-hidden />
      <h2>{t("No process displays yet")}</h2>
      <p>{me.can_edit ? t("Draw the first one: drag equipment from the library, join it with lines and put the plant's values on it.") : t("An editor draws the plant's process displays; they appear here.")}</p>
      {me.can_edit && <button className="button button-primary" onClick={() => navigate("/diagrams/new")}><Plus size={16} /> {t("New process display")}</button>}
    </div>}
    {[...groups.entries()].map(([folderId, rows]) => <section key={folderId || "general"} className="tc-folder-section">
      {groups.size > 1 && <h2 className="pc-overline">{folderName(folderId)}</h2>}
      <div className="pc-grid">
        {rows.map((item) => <article key={item.diagram_id} className="panel tc-list-card">
          <Link to={`/diagrams/${item.diagram_id}`} className="tc-list-main">
            <div>
              <h2>{item.name}</h2>
              <p>{item.description || t("No description.")}</p>
              <span className="tc-chips">{(item.tags ?? []).map((tag) => <span key={tag} className="tag tc-tag">{tag}</span>)}</span>
            </div>
            <ChevronRight size={16} />
          </Link>
          <footer>
            <small>{t("Updated {when}", { when: when(item.updated_at) })}{item.updated_by ? ` ${t("by {user}", { user: item.updated_by })}` : ""}</small>
            {item.can_edit && <span><button className="icon-button" title={t("Delete")} aria-label={t("Delete {name}", { name: item.name })} onClick={() => void remove(item)}><Trash2 size={15} /></button></span>}
          </footer>
        </article>)}
      </div>
    </section>)}
  </>;
}
