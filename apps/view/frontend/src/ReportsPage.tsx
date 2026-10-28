/** The list of reports, by folder (the dashboards' folders): open, start, copy, delete, and the PDF
 * last made. Each report is a document read over one period and sent on a schedule. */
import { Dialog, confirmAction, Pill, errorMessage as message, useAssistantPage } from "@plantcraft/ui";
import { CalendarClock, ChevronRight, Copy, Download, FileText, FolderPlus, Globe2, Plus, Search, Send, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, pdfUrl } from "./api";
import { ExportDialog } from "./ExportDialog";
import { FolderDialog, FolderSelect } from "./FolderDialogs";
import { FolderSections } from "./FolderSections";
import { t } from "./i18n";
import { accessLabel, matchesSearch, stateStatus, when } from "./model";
import { navigate } from "./nav";
import { EMPTY_REPORT, EMPTY_SCHEDULE, newSection, PERIOD_FOR, periodLabel, runState, runStatusLabel } from "./reportModel";
import type { Dashboard, Folder, Me, Report, ReportDraft, Schedule } from "./types";
import { ErrorBox, Heading, Link, Loading } from "./ui";

function ReportCard({ item, me, onCopy, onRemove }: { item: Report; me: Me; onCopy: (item: Report) => void; onRemove: (item: Report) => void }) {
  const last = item.last_run;
  const [downloading, setDownloading] = useState(false);
  return <article className="panel tc-list-card tc-report-card">
    <Link to={`/reports/${item.report_id}`} className="tc-list-main">
      <div>
        <h2>{item.name}</h2>
        <p>{item.description || t("No description.")}</p>
        <span className="tc-chips">
          <span className={`tag${item.schedule.every === "off" ? "" : " tc-tag"}`} title={t("When it is made and sent ({zone})", { zone: item.zone })}><CalendarClock size={11} /> {item.cadence}</span>
          <span className="tag" title={t("What each report covers, ending when it is made")}>{periodLabel(item.period)}</span>
          <span className="tag" title={t("Who receives it in Messages")}><Send size={11} /> {item.recipients.length ? accessLabel(item.recipients) : t("Nobody yet")}</span>
          {(item.public_links ?? 0) > 0 && <span className="tag tc-public" title={t("Anyone with a link reads this report as a web page without signing in")}><Globe2 size={11} /> {t("Public link")}</span>}
        </span>
      </div>
      <ChevronRight size={16} />
    </Link>
    <footer>
      <dl className="tc-report-when">
        <div><dt>{t("Last")}</dt><dd>{last ? <><Pill status={stateStatus(runState(last))} label={runStatusLabel(last)} /> {when(last.started_at)}</> : t("Never made")}</dd></div>
        <div><dt>{t("Next")}</dt><dd>{item.next_run_at ? when(item.next_run_at) : t("When asked")}</dd></div>
      </dl>
      <span>
        <button className="icon-button" title={t("Download")} aria-label={t("Download {name}", { name: item.name })} onClick={() => setDownloading(true)}><Download size={15} /></button>
        {me.can_edit && <button className="icon-button" title={t("Copy")} aria-label={t("Copy {name}", { name: item.name })} onClick={() => onCopy(item)}><Copy size={15} /></button>}
        {item.can_edit && <button className="icon-button" title={t("Delete")} aria-label={t("Delete {name}", { name: item.name })} onClick={() => onRemove(item)}><Trash2 size={15} /></button>}
      </span>
    </footer>
    {downloading && <ExportDialog reportId={item.report_id} pdfHref={last?.status === "done" ? pdfUrl(last) : null} onClose={() => setDownloading(false)} />}
  </article>;
}

/** What a new report starts with: when it is sent, and so what it covers. */
const STARTS: Array<{ id: string; label: string; hint: string; schedule: Schedule }> = [
  { id: "day", label: "Every day", hint: "At 06:00, over the last 24 hours: the shift's day.", schedule: { ...EMPTY_SCHEDULE, every: "day", at: "06:00" } },
  { id: "week", label: "Every week", hint: "On Monday at 07:00, over the last 7 days.", schedule: { ...EMPTY_SCHEDULE, every: "week", at: "07:00", weekday: "mon" } },
  { id: "month", label: "Every month", hint: "On day 1 at 07:00, over the last 30 days.", schedule: { ...EMPTY_SCHEDULE, every: "month", at: "07:00", day: 1 } },
  { id: "off", label: "Only when asked", hint: "Made with Download PDF or Send now; schedule it later.", schedule: EMPTY_SCHEDULE },
];

export function NewReportDialog({ folders, folderId, onClose }: { folders: Folder[]; folderId: string; onClose: () => void }) {
  const [name, setName] = useState("");
  const [folder, setFolder] = useState(folderId);
  const [start, setStart] = useState("day");
  // What it starts from: an empty document, or the pair of a dashboard (its pages and cards).
  const [from, setFrom] = useState("");
  const [dashboards, setDashboards] = useState<Dashboard[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { api.dashboards().then(setDashboards).catch(() => setDashboards([])); }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    const schedule = (STARTS.find((item) => item.id === start) ?? STARTS[0]).schedule;
    setSaving(true);
    try {
      let sections = [{ ...newSection("text", []), text: `# ${name.trim()}\n\n${t("What this report is for, and who reads it.")}` }];
      let description = "";
      if (from) {
        const pair = await api.dashboardAsReport(from);
        sections = pair.sections;
        description = pair.description;
      }
      const draft: ReportDraft = { ...EMPTY_REPORT, name: name.trim(), description, folder_id: folder, schedule, period: PERIOD_FOR[schedule.every], sections };
      const created = await api.createReport(draft);
      navigate(`/reports/${created.report_id}?edit=1`);
    } catch (err) { setError(message(err)); setSaving(false); }
  }
  function pickDashboard(dashboardId: string) {
    setFrom(dashboardId);
    const found = dashboards?.find((item) => item.dashboard_id === dashboardId);
    if (found && !name.trim()) setName(t("{name} report", { name: found.name }).slice(0, 120));
    if (found && found.folder_id && folders.some((item) => item.folder_id === found.folder_id && item.can_edit)) setFolder(found.folder_id);
  }
  return <Dialog title={t("New report")} onClose={onClose} onSubmit={(event) => void submit(event)}>
      {error && <ErrorBox text={error} />}
      <div className="form-grid tc-settings">
        <label>{t("Name")}<input required autoFocus maxLength={120} value={name} placeholder={t("Unit 100 daily report")} onChange={(event) => setName(event.target.value)} /></label>
        <label>{t("Folder")}<FolderSelect folders={folders} value={folder} onChange={setFolder} /></label>
        <fieldset className="tc-wide tc-start">
          <legend>{t("Start from")}</legend>
          <label className="tc-choice"><input type="radio" name="from" checked={!from} onChange={() => setFrom("")} /><span><b>{t("An empty document")}</b><small>{t("A title cell; add text, charts, KPIs, tables and events yourself.")}</small></span></label>
          <label className="tc-choice"><input type="radio" name="from" checked={Boolean(from)} disabled={!dashboards?.length} onChange={() => dashboards?.[0] && pickDashboard(dashboards[0].dashboard_id)} /><span><b>{t("A dashboard")}</b><small>{t("Its pair as a document: each page a heading, each panel a cell, over the report's period.")}</small></span></label>
          {Boolean(from) && <select aria-label={t("The dashboard it starts from")} value={from} onChange={(event) => pickDashboard(event.target.value)}>
            {(dashboards ?? []).map((item) => <option key={item.dashboard_id} value={item.dashboard_id}>{item.name}</option>)}
          </select>}
        </fieldset>
        <fieldset className="tc-wide tc-start">
          <legend>{t("Sent")}</legend>
          {STARTS.map((item) => <label key={item.id} className="tc-choice"><input type="radio" name="start" checked={start === item.id} onChange={() => setStart(item.id)} /><span><b>{t(item.label)}</b><small>{t(item.hint)}</small></span></label>)}
        </fieldset>
      </div>
      <footer><button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button><button className="button button-primary" type="submit" disabled={saving || !name.trim()}>{saving ? t("Saving…") : t("Create and edit")}</button></footer>
      <p className="muted tc-dialog-note">{t("Nobody receives it until you add recipients in its settings.")}</p>
  </Dialog>;
}

export function ReportsPage({ me }: { me: Me }) {
  const [items, setItems] = useState<Report[] | null>(null);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState<string | null>(null);
  const [folderDialog, setFolderDialog] = useState(false);
  const load = useCallback(() => Promise.all([api.reports(), api.folders()]).then(([reports, found]) => { setItems(reports); setFolders(found); }).catch((err) => setError(message(err))), []);
  useEffect(() => { void load(); }, [load]);
  // View's works here (app.toml): ask about the reports.
  useAssistantPage({ place: t("View › Reports"), page: "dashcraft:reports", facts: { reports: items?.length ?? 0 },
    view: { search, reports: (items ?? []).slice(0, 40).map((item) => `${item.name.slice(0, 80)} (${item.cadence}, next ${item.next_run_at ?? "on demand"})`) } });

  async function copy(item: Report) {
    try { const created = await api.copyReport(item.report_id); navigate(`/reports/${created.report_id}?edit=1`); } catch (err) { setError(message(err)); }
  }
  async function remove(item: Report) {
    if (!await confirmAction(t("Delete the report \"{name}\"? The PDFs it made go with it.", { name: item.name }), { confirm: t("Delete"), danger: true })) return;
    try { await api.removeReport(item.report_id); await load(); } catch (err) { setError(message(err)); }
  }

  const shown = (items ?? []).filter((item) => matchesSearch({ ...item, tags: [item.cadence] }, search));

  return <>
    <Heading eyebrow={t("View")} title={t("Reports")}
      detail={t("Documents of notes, charts, KPIs, tables and events over one period: read here, exported to PDF, Word, HTML or Markdown, sent on a schedule.")}
      actions={me.can_edit && <><button className="button button-secondary" onClick={() => setFolderDialog(true)}><FolderPlus size={16} /> {t("New folder")}</button><button className="button button-primary" onClick={() => setCreating("")}><Plus size={16} /> {t("New report")}</button></>} />
    {error && <ErrorBox text={error} />}
    {!items && !error && <Loading />}
    {items && items.length > 0 && <label className="tc-find"><Search size={15} aria-hidden /><input type="search" aria-label={t("Find a report")} placeholder={t("Find by name, description or schedule")} value={search} onChange={(event) => setSearch(event.target.value)} /></label>}
    {items && !items.length && !folders.length && <div className="panel tc-empty-list">
      <FileText size={22} aria-hidden />
      <h2>{t("No reports yet")}</h2>
      <p className="muted">{me.can_edit ? t("A report is a document of panels, notes and events over one period, made into a PDF every day or week and sent to people and groups in Messages.") : t("An editor has not made any report yet.")}</p>
      {me.can_edit && <button className="button button-primary" onClick={() => setCreating("")}><Plus size={15} /> {t("New report")}</button>}
    </div>}
    {items && search && !shown.length && <p className="muted">{t("No report matches \"{text}\".", { text: search })}</p>}
    {items && <FolderSections me={me} folders={folders} items={shown} folderOf={(item) => item.folder_id} search={search} onNew={setCreating} onChanged={() => void load()} onError={setError}
      words={{ count: t("Reports in this folder"), sees: t("Who sees these reports"), edits: t("Who edits these reports"), newHere: t("New report here"), newIn: "New report in {name}", empty: t("No report in this folder yet.") }}
      render={(item) => <ReportCard key={item.report_id} item={item} me={me} onCopy={(found) => void copy(found)} onRemove={(found) => void remove(found)} />} />}
    {items && items.length > 0 && <p className="muted tc-folder-note">{t("Dashboards and reports share these folders, which say who sees and who edits them.")}</p>}
    {folderDialog && <FolderDialog folder={null} onClose={() => setFolderDialog(false)} onSaved={() => { setFolderDialog(false); void load(); }} />}
    {creating !== null && <NewReportDialog folders={folders} folderId={creating} onClose={() => setCreating(null)} />}
  </>;
}
