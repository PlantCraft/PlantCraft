import { confirmAction, errorMessage as message, useAssistantPage } from "@plantcraft/ui";
/** The list of dashboards, by folder: open, create (empty, from a template or a file), copy, delete;
 * folders and who sees and edits them. */
import { BarChart3, ChevronRight, Copy, FolderPlus, Gauge, Globe2, Hash, LineChart, Lock, Monitor, Plus, ScatterChart, Search, Table2, Trash2, Type, Workflow } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { t } from "./i18n";
import { AllLinksDialog } from "./Dialogs";
import { FolderDialog, holdNewDraft, NewDashboardDialog } from "./FolderDialogs";
import { FolderSections } from "./FolderSections";
import { matchesSearch, refreshLabel, when } from "./model";
import { navigate } from "./nav";
import type { Dashboard, DashboardDraft, Folder, Kind, Me } from "./types";
import { ErrorBox, Heading, Link, Loading } from "./ui";

const ICONS: Record<Kind, typeof Gauge> = { stat: Hash, gauge: Gauge, trend: LineChart, bar: BarChart3, table: Table2, scatter: ScatterChart, text: Type, diagram: Workflow };

function DashboardCard({ item, me, onCopy, onRemove }: { item: Dashboard; me: Me; onCopy: (item: Dashboard) => void; onRemove: (item: Dashboard) => void }) {
  return <article className="panel tc-list-card">
    <Link to={`/d/${item.dashboard_id}`} className="tc-list-main">
      <div>
        <h2>{item.name}</h2>
        <p>{item.description || t("No description.")}</p>
        <span className="tc-chips">
          {(item.variables ?? []).filter((variable) => variable.type === "asset").slice(0, 2).map((variable) => <span key={variable.name} className="tag">{t("per {kind}", { kind: variable.label || variable.asset_kind || variable.name })}</span>)}
          {item.pages.length > 1 && <span className="tag">{t("{n} pages", { n: item.pages.length })}</span>}
          {(item.tags ?? []).map((tag) => <span key={tag} className="tag tc-tag">{tag}</span>)}
          {item.builtin && <span className="tag" title={t("Kept by the suite: copy it to change it")}><Lock size={11} /> {t("Kept by the suite")}</span>}
          {(item.public_links ?? 0) > 0 && <span className="tag tc-public" title={t("Anyone with a link sees this dashboard without signing in")}><Globe2 size={11} /> {t("Public link")}</span>}
        </span>
      </div>
      <ChevronRight size={16} />
    </Link>
    <div className="tc-mini" aria-hidden>{item.cards.slice(0, 12).map((card) => { const Icon = ICONS[card.kind]; return <span key={card.card_id} style={{ gridColumn: `span ${card.width}` }}><Icon size={12} /></span>; })}</div>
    <footer>
      <small>{t("{count} panels", { count: item.cards.length })} · {refreshLabel(item.refresh_seconds)} · {t("updated {when}", { when: when(item.updated_at) })}{item.updated_by ? ` ${t("by {user}", { user: item.updated_by })}` : ""}</small>
      <span>
        <Link to={`/d/${item.dashboard_id}?screen=1`} className="icon-button"><Monitor size={15} aria-label={t("Full screen")} /></Link>
        {me.can_edit && <button className="icon-button" title={t("Copy")} aria-label={t("Copy {name}", { name: item.name })} onClick={() => onCopy(item)}><Copy size={15} /></button>}
        {item.can_edit && <button className="icon-button" title={t("Delete")} aria-label={t("Delete {name}", { name: item.name })} onClick={() => onRemove(item)}><Trash2 size={15} /></button>}
      </span>
    </footer>
  </article>;
}

export function DashboardsPage({ me }: { me: Me }) {
  const [items, setItems] = useState<Dashboard[] | null>(null);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState<string | null>(null);
  const [folderDialog, setFolderDialog] = useState(false);
  const [linksDialog, setLinksDialog] = useState(false);
  const load = useCallback(() => Promise.all([api.dashboards(), api.folders()]).then(([dashboards, found]) => { setItems(dashboards); setFolders(found); }).catch((err) => setError(message(err))), []);
  useEffect(() => { void load(); }, [load]);
  // View's works here (app.toml): find a dashboard, suggest a new one.
  useAssistantPage({ place: t("View › Dashboards"), page: "dashcraft:dashboards", facts: { dashboards: items?.length ?? 0 },
    view: { search, dashboards: (items ?? []).slice(0, 40).map((item) => `${item.name.slice(0, 80)}${item.description ? `: ${item.description.slice(0, 100)}` : ""}`) } });

  function start(draft: DashboardDraft) {
    holdNewDraft(draft);
    navigate("/d/new?edit=1");
  }
  async function copy(item: Dashboard) {
    try { const created = await api.copy(item.dashboard_id); navigate(`/d/${created.dashboard_id}?edit=1`); } catch (err) { setError(message(err)); }
  }
  async function remove(item: Dashboard) {
    if (!await confirmAction(t("Delete the dashboard \"{name}\"? Its panels and public links go with it.", { name: item.name }), { confirm: t("Delete"), danger: true })) return;
    try { await api.remove(item.dashboard_id); await load(); } catch (err) { setError(message(err)); }
  }

  const shown = (items ?? []).filter((item) => matchesSearch(item, search));

  return <>
    <Heading eyebrow={t("View")} title={t("Dashboards")}
      detail={t("Screens of KPIs, trends, bars and tables over the signals and assets of PlantCraft, in folders that say who sees them.")}
      actions={me.can_edit && <>{me.is_admin && me.public_links && <button className="button button-secondary" onClick={() => setLinksDialog(true)}><Globe2 size={16} /> {t("Public links")}</button>}<button className="button button-secondary" onClick={() => setFolderDialog(true)}><FolderPlus size={16} /> {t("New folder")}</button><button className="button button-primary" onClick={() => setCreating("")}><Plus size={16} /> {t("New dashboard")}</button></>} />
    {error && <ErrorBox text={error} />}
    {!items && !error && <Loading />}
    {items && items.length > 0 && <label className="tc-find"><Search size={15} aria-hidden /><input type="search" aria-label={t("Find a dashboard")} placeholder={t("Find by name, description or label")} value={search} onChange={(event) => setSearch(event.target.value)} /></label>}
    {items && !items.length && !folders.length && <div className="panel tc-empty-list">
      <h2>{t("No dashboards yet")}</h2>
      <p className="muted">{me.can_edit ? t("New dashboard starts an empty grid, a template built from the plant's assets, or a file exported from View.") : t("An editor has not made any dashboard yet.")}</p>
    </div>}
    {items && search && !shown.length && <p className="muted">{t("No dashboard matches \"{text}\".", { text: search })}</p>}
    {items && <FolderSections me={me} folders={folders} items={shown} folderOf={(item) => item.folder_id ?? ""} search={search} onNew={setCreating} onChanged={() => void load()} onError={setError}
      words={{ count: t("Dashboards in this folder"), sees: t("Who sees these dashboards"), edits: t("Who edits these dashboards"), newHere: t("New dashboard here"), newIn: "New dashboard in {name}", empty: t("No dashboard in this folder yet.") }}
      render={(item) => <DashboardCard key={item.dashboard_id} item={item} me={me} onCopy={(found) => void copy(found)} onRemove={(found) => void remove(found)} />} />}
    {creating !== null && <NewDashboardDialog folders={folders} folderId={creating} onClose={() => setCreating(null)} onStart={start} />}
    {folderDialog && <FolderDialog folder={null} onClose={() => setFolderDialog(false)} onSaved={() => { setFolderDialog(false); void load(); }} />}
    {linksDialog && <AllLinksDialog onClose={() => { setLinksDialog(false); void load(); }} />}
  </>;
}
