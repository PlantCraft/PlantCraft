/** One report: the document as it reads now (its sections over its period), the PDFs it made
 * and sent, Download PDF and Send now, and the editor of its sections and settings. */
import { Dialog, confirmAction, ApiError, MultiSelect, PageTabs, Pill, RecipientPicker, DataTable, errorMessage as message, renderMarkdown, useAssistantPage, type DataColumn, timeZoneLabel } from "@plantcraft/ui";
import { AlertTriangle, ArrowDown, ArrowUp, CalendarClock, Check, Columns2, Download, FileText, Globe2, LayoutList, ListOrdered, ListTree, LoaderCircle, Pencil, Plus, RefreshCw, Rows3, Save, Send, Settings2, Siren, Sparkles, SquareSplitVertical, Trash2, Type, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type FormEvent, type KeyboardEvent } from "react";
import { api, pdfUrl, type CardSource } from "./api";
import { AlarmsDialog, AlarmsView } from "./AlarmsSection";
import { AssistantDialog, AssistantView } from "./AssistantSection";
import { CardEditor } from "./CardEditor";
import { CardView } from "./CardView";
import { ShareDialog } from "./Dialogs";
import { ExportDialog } from "./ExportDialog";
import { FolderSelect } from "./FolderDialogs";
import { formatDate, t } from "./i18n";
import { accessLabel, cardPixels, stateStatus, when, windowLabel } from "./model";
import { cadenceLabel, CLOSED_LABELS, deliveredLabel, insertSection, MAX_SECTIONS, MAX_TEXT, moveSection, outlineOf, newSection, PERIOD_FOR, PERIODS, pdfSize, periodLabel, periodRange, replaceSection, reportDraftOf, runState, runStatusLabel, sectionName, SECTION_LABELS, TRIGGER_LABELS, WEEKDAY_NAMES, WEEKDAYS } from "./reportModel";
import type { Card, CardData, Directory, EventKind, EventsData, Folder, Me, Report, ReportDraft, ReportRun, Section, SectionData, SectionKind } from "./types";
import type { OutlineEntry } from "./reportModel";
import { ErrorBox, Link, Loading } from "./ui";

type Tab = "report" | "sent";

function readQuery() {
  const params = new URLSearchParams(window.location.search);
  return { edit: params.get("edit") === "1", tab: (params.get("tab") === "sent" ? "sent" : "report") as Tab, run: params.get("run") };
}
function writeQuery(next: { edit?: boolean; tab?: Tab; run?: string | null }) {
  const params = new URLSearchParams();
  if (next.edit) params.set("edit", "1");
  if (next.tab === "sent") params.set("tab", "sent");
  if (next.run) params.set("run", next.run);
  const text = params.toString();
  return text ? `?${text}` : "";
}

/** Reads one section, again on every `tick`. */
function useSection(read: () => Promise<SectionData>, key: string, tick: number) {
  const [state, setState] = useState<{ data: SectionData | null; error: string; loading: boolean }>({ data: null, error: "", loading: true });
  useEffect(() => {
    let live = true;
    setState((current) => ({ ...current, loading: true }));
    read().then((data) => { if (live) setState({ data, error: "", loading: false }); })
      .catch((err) => { if (live) setState({ data: null, error: message(err), loading: false }); });
    return () => { live = false; };
    // `read` changes identity every render; `key` names what it reads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, tick]);
  return state;
}

const SEVERITY: Record<string, string> = { critical: "critical", error: "critical", warning: "medium", info: "inactive" };

/** An events section: how many of each kind in the period, and the latest of them. */
function EventsView({ section, read, tick }: { section: Section; read: () => Promise<SectionData>; tick: number }) {
  const { data, error, loading } = useSection(read, JSON.stringify(section), tick);
  const events = (data?.data as EventsData | null) ?? null;
  const failed = error || data?.error;
  return <div className="tc-report-events">
    <h3>{section.title || t("Events")}{loading && <LoaderCircle size={13} className="spin" />}</h3>
    {failed ? <div className="tc-card-error" role="alert"><AlertTriangle size={15} /> {failed}</div>
      : !events ? <div className="tc-card-loading"><LoaderCircle className="spin" /></div>
      : <>
        {!events.groups && <div className="tc-report-counts">{events.counts.map((count) => <span key={count.kind} className="tc-report-count"><b className="pc-num">{count.count}{count.more ? "+" : ""}</b><small>{count.title}</small></span>)}</div>}
        {events.groups ? <EventGroups events={events} /> : events.events.length ? <table className="tc-report-table">
          <thead><tr><th>{t("When")}</th><th>{t("Event")}</th><th>{t("About")}</th><th>{t("What happened")}</th></tr></thead>
          <tbody>{events.events.map((row, index) => <tr key={`${row.at}-${index}`}>
            <td className="pc-num">{formatDate(row.at, { dateStyle: "short", timeStyle: "short" })}</td>
            <td><Pill status={SEVERITY[row.severity] ?? "inactive"} label={row.title} /></td>
            <td>{row.subject_name || row.subject}</td>
            <td>{row.summary}</td>
          </tr>)}</tbody>
        </table> : <p className="muted">{t("No such event in this period.")}</p>}
        {!events.groups && events.total > events.events.length && <small className="muted">{t("The latest {n} of {total}.", { n: events.events.length, total: events.total })}</small>}
      </>}
  </div>;
}

/** The ranked groups of an events section that counts its events, and the largest named. */
function EventGroups({ events }: { events: EventsData }) {
  const groups = events.groups ?? [];
  if (!groups.length) return <p className="muted">{t("No such event in this period.")}</p>;
  const top = groups[0];
  const all = events.group_total ?? groups.length;
  const share = (value: number) => (Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1));
  return <>
    <p className="tc-report-lead">{t("Most often: {label}, {count} of {total} ({share}%).", { label: top.label, count: top.count, total: events.total, share: share(top.share) })}{all > 1 ? ` ${t("{n} in all.", { n: all })}` : ""}</p>
    <table className="tc-report-table">
      <thead><tr><th className="pc-num">#</th><th>{events.group_head || t("Group")}</th><th className="pc-num">{t("Count")}</th><th className="pc-num">{t("Share")}</th><th>{t("Latest")}</th><th>{t("Latest event")}</th></tr></thead>
      <tbody>{groups.map((group, index) => <tr key={group.key || `none-${index}`}>
        <td className="pc-num">{index + 1}</td>
        <td><Pill status={SEVERITY[group.severity] ?? "inactive"} label={group.label} /></td>
        <td className="pc-num"><b>{group.count}</b></td>
        <td className="pc-num">{share(group.share)}%</td>
        <td className="pc-num">{group.last ? formatDate(group.last, { dateStyle: "short", timeStyle: "short" }) : ""}</td>
        <td>{group.summary}</td>
      </tr>)}</tbody>
    </table>
    {all > groups.length && <small className="muted">{t("The {n} largest of {total} groups are listed.", { n: groups.length, total: all })}</small>}
  </>;
}

function SectionBody({ section, read, source, tick, editing, reportId = "", canEdit = false }: { section: Section; read: () => Promise<SectionData>; source: CardSource; tick: number; editing: boolean; reportId?: string; canEdit?: boolean }) {
  if (section.kind === "text") return <div className="tc-report-text"><div className="pc-markdown">{renderMarkdown(section.text)}</div></div>;
  if (section.kind === "break") return editing ? <div className="tc-report-break"><SquareSplitVertical size={14} aria-hidden /> {t("The PDF starts a new page here")}</div> : null;
  if (section.kind === "events") return <EventsView section={section} read={read} tick={tick} />;
  if (section.kind === "alarms") return <AlarmsView section={section} read={read} tick={tick} />;
  if (section.kind === "assistant") return <AssistantView section={section} read={read} tick={tick} reportId={reportId} canEdit={canEdit} editing={editing} />;
  if (!section.card) return null;
  return <div className="tc-report-card" style={{ height: `${reportCardPixels(section.card)}px` } as CSSProperties}>
    <CardView card={section.card} source={source} vars={{}} window={null} tick={tick} />
  </div>;
}

/** A card's height in a report: its own, and a table as tall as its rows (a page scrolls, a
 * report does not hide rows). */
function reportCardPixels(card: Card): number {
  const own = cardPixels(card.height);
  return card.kind === "table" ? Math.max(own, 80 + 62 * (card.items.length + 1)) : own;
}

/** A text cell being written, in place (a notebook's Markdown cell): the Markdown, and how it
 * reads, side by side. Shift+Enter or Esc finishes it. */
function TextCell({ section, onChange, onDone }: { section: Section; onChange: (section: Section) => void; onDone: () => void }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { const area = ref.current; if (area) { area.focus(); area.setSelectionRange(area.value.length, area.value.length); } }, []);
  useLayoutEffect(() => { const area = ref.current; if (area) { area.style.height = "auto"; area.style.height = `${Math.max(area.scrollHeight, 96)}px`; } }, [section.text]);
  function keys(event: KeyboardEvent<HTMLTextAreaElement>) {
    if ((event.key === "Enter" && event.shiftKey) || event.key === "Escape") { event.preventDefault(); onDone(); }
  }
  return <div className="tc-report-cell-edit">
    <label className="tc-report-md"><span className="sr-only">{t("Markdown of the cell")}</span>
      <textarea ref={ref} maxLength={MAX_TEXT} value={section.text} spellCheck onKeyDown={keys} onChange={(event) => onChange({ ...section, text: event.target.value })}
        placeholder={t("# Heading, ## Subheading, ### and #### below them; **bold**, *italic*, - lists, 1. numbered, | tables |, > quotes.")} />
      <small className="muted">{t("Markdown: # to #### make the sections of the side navigation and of the Word and HTML files. Shift+Enter finishes.")}</small>
    </label>
    <div className="tc-report-text tc-report-text-preview" aria-live="polite"><small className="pc-overline">{t("Preview")}</small>{section.text.trim() ? <div className="pc-markdown">{renderMarkdown(section.text)}</div> : <p className="muted">{t("Nothing written yet.")}</p>}</div>
    <div className="tc-report-cell-done"><button type="button" className="button button-secondary button-small" onClick={onDone}><Check size={14} /> {t("Done")}</button></div>
  </div>;
}

/** The headings of the text cells, beside the report: where each section is, and where the
 * reader is now. */
function Outline({ entries }: { entries: OutlineEntry[] }) {
  const [here, setHere] = useState(0);
  const heading = useCallback((entry: OutlineEntry) => document.querySelector(`[data-section="${CSS.escape(entry.sectionId)}"] .pc-markdown`)?.querySelectorAll("h1, h2, h3, h4")[entry.nth] as HTMLElement | undefined, []);
  useEffect(() => {
    const found = entries.map(heading).filter((item): item is HTMLElement => Boolean(item));
    if (!found.length || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(() => {
      let last = 0;
      found.forEach((item, index) => { if (item.getBoundingClientRect().top < 140) last = index; });
      setHere(last);
    }, { rootMargin: "0px 0px -55% 0px" });
    found.forEach((item) => observer.observe(item));
    return () => observer.disconnect();
  }, [entries, heading]);
  return <nav className="tc-report-outline" aria-label={t("Sections of the report")}>
    <span className="pc-overline"><ListTree size={13} aria-hidden /> {t("Sections")}</span>
    <ol>{entries.map((entry, index) => <li key={`${entry.sectionId}-${entry.nth}`} className={`tc-outline-l${entry.level}`}>
      <a href={`#${entry.sectionId}`} className={index === here ? "tc-outline-here" : undefined} aria-current={index === here ? "location" : undefined}
        onClick={(event) => { event.preventDefault(); setHere(index); heading(entry)?.scrollIntoView({ behavior: "smooth", block: "start" }); }}>{entry.text}</a>
    </li>)}</ol>
  </nav>;
}

/** What an events section shows: its latest events, or their count by one field, ranked. */
const GROUPINGS: Array<[string, string]> = [["", "The latest events"], ["subject", "Count by what they are about"], ["kind", "Count by kind"], ["severity", "Count by severity"]];

/** An events section: which events of the installed apps it lists. */
function EventsDialog({ section, onSave, onClose }: { section: Section; onSave: (section: Section) => void; onClose: () => void }) {
  const [value, setValue] = useState(section);
  const [kinds, setKinds] = useState<EventKind[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.eventKinds().then(setKinds).catch((err) => { setKinds([]); setError(message(err)); }); }, []);
  const spec = value.events ?? { kinds: [], limit: 20 };
  const options = (kinds ?? []).map((kind) => ({ id: kind.kind, label: `${kind.title} · ${kind.app}` }));
  for (const kind of spec.kinds) if (!options.some((option) => option.id === kind)) options.push({ id: kind, label: kind });
  return <Dialog title={t("Events section")} onClose={onClose} onSubmit={() => onSave(value)}>
      {error && <ErrorBox text={error} />}
      <div className="form-grid tc-settings">
        <label className="tc-wide">{t("Title")}<input autoFocus maxLength={120} value={value.title} onChange={(event) => setValue({ ...value, title: event.target.value })} /></label>
        <div className="tc-wide tc-field"><span>{t("Events")}</span>
          {kinds === null ? <small className="muted">{t("Reading the events the apps declare…")}</small>
            : <MultiSelect label={t("Events")} allLabel={t("Choose…")} options={options} value={spec.kinds} onChange={(picked) => setValue({ ...value, events: { ...spec, kinds: picked.slice(0, 10) } })} />}
          <small className="muted">{t("Up to 10 kinds. The section counts each kind in the period and lists the latest.")}</small>
        </div>
        <label>{t("Show")}<select value={spec.group_by ?? ""} onChange={(event) => setValue({ ...value, events: { ...spec, group_by: event.target.value } })}>
          {GROUPINGS.map(([id, label]) => <option key={id} value={id}>{t(label)}</option>)}
          {spec.group_by && !GROUPINGS.some(([id]) => id === spec.group_by) && <option value={spec.group_by}>{t("Counted by {field}", { field: spec.group_by })}</option>}
        </select></label>
        <label>{spec.group_by ? t("Groups at most") : t("Listed at most")}<input type="number" min={1} max={100} value={spec.limit} onChange={(event) => setValue({ ...value, events: { ...spec, limit: Math.max(1, Math.min(100, Number(event.target.value) || 20)) } })} /></label>
      </div>
      <footer><button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button><button className="button button-primary" type="submit" disabled={!spec.kinds.length}>{t("Apply")}</button></footer>
  </Dialog>;
}

/** Name, folder, period, schedule and recipients. */
function ReportSettingsDialog({ draft, folders, zone, onApply, onClose }: { draft: ReportDraft; folders: Folder[]; zone: string; onApply: (draft: ReportDraft) => void; onClose: () => void }) {
  const [value, setValue] = useState(draft);
  const [directory, setDirectory] = useState<Directory | null>(null);
  useEffect(() => { api.directory().then(setDirectory).catch(() => setDirectory({ people: [], groups: [] })); }, []);
  const schedule = value.schedule;
  const closed = schedule.every !== "off" && Boolean(schedule.closed);
  const setEvery = (every: ReportDraft["schedule"]["every"]) => setValue({ ...value, schedule: { ...schedule, every }, period: every === schedule.every ? value.period : PERIOD_FOR[every] });
  function submit(event: FormEvent) { event.preventDefault(); onApply({ ...value, name: value.name.trim() }); }
  return <Dialog title={t("Report settings")} onClose={onClose} onSubmit={submit}>
      <div className="form-grid tc-settings">
        <label>{t("Name")}<input required maxLength={120} value={value.name} onChange={(event) => setValue({ ...value, name: event.target.value })} /></label>
        <label>{t("Folder")}<FolderSelect folders={folders} value={value.folder_id} onChange={(folder_id) => setValue({ ...value, folder_id })} /></label>
        <label className="tc-wide">{t("Description")}<input maxLength={500} value={value.description} onChange={(event) => setValue({ ...value, description: event.target.value })} /></label>
        <fieldset className="tc-wide tc-report-schedule">
          <legend>{t("When it is made and sent")}</legend>
          <label>{t("Repeat")}<select value={schedule.every} onChange={(event) => setEvery(event.target.value as typeof schedule.every)}>
            <option value="off">{t("Not scheduled")}</option><option value="day">{t("Every day")}</option><option value="week">{t("Every week")}</option><option value="fortnight">{t("Every other week")}</option><option value="month">{t("Every month")}</option><option value="quarter">{t("Every quarter")}</option>
          </select></label>
          {(schedule.every === "week" || schedule.every === "fortnight") && <label>{t("On")}<select value={schedule.weekday} onChange={(event) => setValue({ ...value, schedule: { ...schedule, weekday: event.target.value as typeof schedule.weekday } })}>{WEEKDAYS.map((day) => <option key={day} value={day}>{t(WEEKDAY_NAMES[day])}</option>)}</select></label>}
          {(schedule.every === "month" || schedule.every === "quarter") && <label>{t("On day")}<select value={schedule.day} onChange={(event) => setValue({ ...value, schedule: { ...schedule, day: Number(event.target.value) } })}>{Array.from({ length: 28 }, (_, index) => index + 1).map((day) => <option key={day} value={day}>{day}</option>)}</select></label>}
          {schedule.every !== "off" && <label>{t("At")}<input type="time" required value={schedule.at} onChange={(event) => setValue({ ...value, schedule: { ...schedule, at: event.target.value } })} /></label>}
          {closed ? <label>{t("Covers")}<input readOnly value={t(CLOSED_LABELS[schedule.every])} /></label>
            : <label>{t("Covers")}<select value={value.period} onChange={(event) => setValue({ ...value, period: event.target.value })}>
              {!PERIODS.includes(value.period) && <option value={value.period}>{periodLabel(value.period)}</option>}
              {PERIODS.map((period) => <option key={period} value={period}>{periodLabel(period)}</option>)}
            </select></label>}
          {schedule.every !== "off" && <label className="check tc-wide"><input type="checkbox" checked={closed} onChange={() => setValue({ ...value, schedule: { ...schedule, closed: !closed } })} /> {t("Whole calendar periods (last week, last month), not the time up to the send")}</label>}
          <small className="muted tc-wide">{schedule.every === "off" ? t("Made only with Download PDF or Send now.") : closed ? t("{cadence}, in the installation's time zone ({zone}), over {period}.", { cadence: cadenceLabel(schedule), zone, period: t(CLOSED_LABELS[schedule.every]).toLowerCase() }) : t("{cadence}, in the installation's time zone ({zone}), over {period} up to then.", { cadence: cadenceLabel(schedule), zone, period: periodLabel(value.period).toLowerCase() })}</small>
        </fieldset>
        <div className="tc-wide tc-field"><span>{t("Sent to")}</span>
          <RecipientPicker label={t("Sent to")} value={value.recipients} onChange={(recipients) => setValue({ ...value, recipients })} people={directory?.people ?? []} groups={directory?.groups ?? []} placeholder={t("A person or a group of the platform…")} />
          <small className="muted">{t("Each send reaches them in Messages › Notifications, with the PDF one click away. Only people who may see the report's folder open it.")}</small>
        </div>
        <label className="tc-wide tc-check"><input type="checkbox" checked={value.email} onChange={(event) => setValue({ ...value, email: event.target.checked })} /> {t("Also by email, where PlantCraft sends email and the person allows it")}</label>
      </div>
      <footer><button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button><button className="button button-primary" type="submit">{t("Apply")}</button></footer>
  </Dialog>;
}

/** The PDFs the report made: when, over what, how, to whom, and the file. */
function RunsTable({ runs, highlight }: { runs: ReportRun[]; highlight: string | null }) {
  const columns: DataColumn<ReportRun>[] = [
    { key: "started_at", label: t("Made"), sort: (run) => run.started_at, render: (run) => formatDate(run.started_at, { dateStyle: "medium", timeStyle: "short" }) },
    { key: "period", label: t("Covers"), render: (run) => `${formatDate(run.period_start, { dateStyle: "short", timeStyle: "short" })} – ${formatDate(run.period_end, { dateStyle: "short", timeStyle: "short" })}` },
    { key: "trigger", label: t("How"), sort: (run) => run.trigger, render: (run) => <>{t(TRIGGER_LABELS[run.trigger])}{run.requested_by ? <small className="muted"> · {run.requested_by}</small> : null}</>, filter: { options: (["schedule", "send", "download"] as const).map((value) => ({ value, label: t(TRIGGER_LABELS[value]) })) } },
    { key: "delivered", label: t("Reached"), numeric: true, sort: (run) => run.delivered, render: deliveredLabel },
    { key: "status", label: t("Status"), sort: (run) => runState(run), render: (run) => <span title={run.error || run.summary}><Pill status={stateStatus(runState(run))} label={runStatusLabel(run)} /></span> },
    { key: "pdf", label: t("PDF"), render: (run) => (run.status === "done" ? <span className="tc-report-pdf"><a href={pdfUrl(run)} target="_blank" rel="noreferrer">{t("Open")}</a><a href={pdfUrl(run, true)} aria-label={t("Download")} title={t("Download")}><Download size={14} /></a><small className="muted">{pdfSize(run.pdf_bytes)}</small></span> : <small className="muted">{run.error || "—"}</small>) },
  ];
  return <DataTable rows={runs} columns={columns} rowKey={(run) => run.run_id} label={t("PDFs made")} initialSort={{ key: "started_at", descending: true }} pageSizes={[10, 25, 100]}
    rowClassName={(run) => (run.run_id === highlight ? "tc-row-picked" : undefined)}
    empty={<p className="muted">{t("No PDF yet: Download PDF makes one now, and the schedule sends the next.")}</p>} />;
}

const ADD: Array<{ kind: SectionKind; icon: typeof Type; hint: string }> = [
  { kind: "text", icon: Type, hint: "Markdown: headings, notes, lists, tables" },
  { kind: "card", icon: LayoutList, hint: "A chart, KPIs or a table" },
  { kind: "events", icon: ListOrdered, hint: "Alarms, runs, other events" },
  { kind: "alarms", icon: Siren, hint: "ISA-18.2 load, floods and response from Alarms" },
  { kind: "assistant", icon: Sparkles, hint: "Written by the assistant from the picked assets" },
  { kind: "break", icon: SquareSplitVertical, hint: "A new page in the PDF" },
];

export function ReportPage({ reportId, me }: { reportId: string; me: Me }) {
  const [saved, setSaved] = useState<Report | null>(null);
  const [draft, setDraft] = useState<ReportDraft | null>(null);
  const [runs, setRuns] = useState<ReportRun[] | null>(null);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [tab, setTab] = useState<Tab>(() => (readQuery().run ? "sent" : readQuery().tab));
  const [highlight] = useState(() => readQuery().run);
  const [tick, setTick] = useState(0);
  const [stamp, setStamp] = useState(() => new Date());
  const [editing, setEditing] = useState<Section | null>(null);
  // The text cell being written in place, and where the next new cell goes (null: at the end).
  const [writing, setWriting] = useState<string | null>(null);
  const [insertAt, setInsertAt] = useState<number | null>(null);
  const [adding, setAdding] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [settings, setSettings] = useState(false);
  const [busy, setBusy] = useState<"" | "pdf" | "send" | "save">("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState<{ text: string; run?: ReportRun } | null>(null);
  const canEdit = me.can_edit && saved?.can_edit !== false;

  const loadRuns = useCallback(() => api.reportRuns(reportId).then(setRuns).catch(() => setRuns([])), [reportId]);
  useEffect(() => {
    api.report(reportId).then((found) => {
      setSaved(found);
      if (readQuery().edit && me.can_edit && found.can_edit) setDraft(reportDraftOf(found));
    }).catch((err) => setError(message(err)));
    void loadRuns();
  }, [reportId, me.can_edit, loadRuns]);
  useEffect(() => { if (me.can_edit) api.folders().then(setFolders).catch(() => setFolders([])); }, [me.can_edit]);

  const go = useCallback((next: { edit?: boolean; tab?: Tab }) => {
    window.history.replaceState({}, "", `${window.location.pathname}${writeQuery({ edit: next.edit, tab: next.tab })}`);
  }, []);
  const shown = useMemo(() => draft ?? (saved ? reportDraftOf(saved) : null), [draft, saved]);
  // Read again: the sections, and what the report covers now.
  const refresh = useCallback(() => {
    setTick((value) => value + 1);
    setStamp(new Date());
    api.report(reportId).then(setSaved).catch(() => undefined);
  }, [reportId]);

  // A saved section reads as the PDF will (View's token); a draft's with the editor's own.
  const readOf = useCallback((section: Section) => () => (draft ? api.reportPreview(section, draft.period) : api.reportSection(reportId, section.section_id, null)), [draft, reportId]);
  const source: CardSource = useMemo(() => ({
    card: async (cardId) => {
      const section = shown?.sections.find((item) => item.card?.card_id === cardId);
      if (!section) throw new Error(t("Panel not found."));
      const read = await readOf(section)();
      if (read.error) throw new Error(read.error);
      return read.data as CardData;
    },
    options: () => Promise.resolve([]),
  }), [shown, readOf]);

  // View's works for a report (app.toml: a summary for the shift, what it should also show).
  useAssistantPage(shown ? {
    page: "dashcraft:report", subject: `report:${reportId}`, title: shown.name, place: t("Reports › {name}", { name: shown.name }),
    context: [`Report ${shown.name}${shown.description ? `: ${shown.description}` : ""}.`,
      `Covers ${periodLabel(shown.period).toLowerCase()}; ${cadenceLabel(shown.schedule).toLowerCase()}.`,
      `Sections: ${shown.sections.map((section) => `${t(SECTION_LABELS[section.kind])}: ${sectionName(section)}`).join("; ")}.`].join("\n"),
  } : null);

  if (error && !saved) return <ErrorBox text={error} />;
  if (!saved || !shown) return <Loading />;

  const setSections = (sections: Section[]) => setDraft((current) => (current ? { ...current, sections } : current));
  const startEditing = () => { setDraft(reportDraftOf(saved)); setTab("report"); go({ edit: true }); setNotice(null); };
  const stopEditing = () => { setDraft(null); go({ edit: false, tab }); };

  async function save(force = false) {
    if (!draft) return;
    setBusy("save");
    setError("");
    try {
      const result = await api.saveReport(reportId, draft, force ? null : saved?.updated_at);
      setSaved(result);
      setDraft(null);
      go({ edit: false });
      setNotice({ text: t("Saved.") });
      refresh();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && await confirmAction(`${err.message}\n\n${t("Replace their version with yours?")}`, { confirm: t("Replace") })) { setBusy(""); return save(true); }
      setError(message(err));
    } finally { setBusy(""); }
  }
  async function applySettings(next: ReportDraft) {
    setSettings(false);
    if (draft) { setDraft(next); return; }
    if (!saved) return;
    try {
      const result = await api.saveReport(reportId, { ...reportDraftOf(saved), ...next, sections: saved.sections }, saved.updated_at);
      setSaved(result);
      setNotice({ text: t("Saved.") });
    } catch (err) { setError(message(err)); }
  }
  async function makePdf() {
    setBusy("pdf");
    setError("");
    try {
      const run = await api.makePdf(reportId);
      await loadRuns();
      if (run.status !== "done") { setError(run.error || t("The PDF could not be made.")); return; }
      const link = document.createElement("a");
      link.href = pdfUrl(run, true);
      link.rel = "noreferrer";
      document.body.append(link);
      link.click();
      link.remove();
      setNotice({ text: run.problems ? t("PDF made, but {summary}", { summary: run.summary.toLowerCase() }) : t("PDF made."), run });
    } catch (err) { setError(message(err)); } finally { setBusy(""); }
  }
  async function sendNow() {
    if (!saved) return;
    if (!await confirmAction(t("Send \"{name}\" now to {who}?", { name: saved.name, who: accessLabel(saved.recipients).toLowerCase() }), { confirm: t("Send") })) return;
    setBusy("send");
    setError("");
    try {
      const run = await api.sendReport(reportId);
      await loadRuns();
      const refreshed = await api.report(reportId);
      setSaved(refreshed);
      if (run.status !== "done") setError(run.error || t("The report could not be made."));
      else setNotice({ text: run.delivered === 1 ? t("Sent to 1 person in Messages.") : t("Sent to {n} people in Messages.", { n: run.delivered }), run });
    } catch (err) { setError(message(err)); } finally { setBusy(""); }
  }
  /** A new cell at `at` (after the cell whose "Add below" was used), else at the end. */
  function add(kind: SectionKind, at: number | null = null) {
    if (!draft) return;
    const section = newSection(kind, draft.sections);
    setAdding(null);
    if (kind === "break" || kind === "text") {
      setSections(insertSection(draft.sections, section, at));
      if (kind === "text") setWriting(section.section_id);
      return;
    }
    setInsertAt(at);
    setEditing(section);
  }
  function applySection(section: Section) {
    if (!draft) return;
    const known = draft.sections.some((item) => item.section_id === section.section_id);
    setSections(known ? replaceSection(draft.sections, section) : insertSection(draft.sections, section, insertAt));
    setEditing(null);
    setInsertAt(null);
  }
  /** A text cell finished: kept, or dropped when nothing was written. */
  function doneWriting(section: Section) {
    setWriting(null);
    if (draft && !section.text.replace(/^#+\s*$/gm, "").trim()) setSections(draft.sections.filter((item) => item.section_id !== section.section_id));
  }

  // The period as the server reads it now; a draft's new period ends at the same moment.
  const range = draft && draft.period !== saved.period ? periodRange(draft.period, new Date(saved.covers.end)) : { start: new Date(saved.covers.start), end: new Date(saved.covers.end) };
  const sectionsFull = (draft?.sections.length ?? 0) >= MAX_SECTIONS;
  const outline = outlineOf(shown.sections);
  const tabs = [{ to: "report", label: t("Report"), active: tab === "report" }, { to: "sent", label: runs?.length ? t("Sent ({n})", { n: runs.length }) : t("Sent"), active: tab === "sent" }];
  return <div className="tc-report-page">
    <div className="tc-head">
      <div className="tc-title">
        <Link to="/reports" className="breadcrumb">{t("Reports")}</Link>
        <h1>{shown.name}{draft && <span className="tag">{t("Editing")}</span>}</h1>
        <p className="tc-report-facts">
          <span><CalendarClock size={14} aria-hidden /> {draft ? cadenceLabel(draft.schedule) : saved.cadence}</span>
          <span>{periodLabel(shown.period)}</span>
          <span><Send size={14} aria-hidden /> {shown.recipients.length ? accessLabel(shown.recipients) : t("Nobody yet")}</span>
          {!draft && saved.next_run_at && <span>{t("Next send {when}", { when: when(saved.next_run_at) })}</span>}
        </p>
      </div>
      <div className="tc-toolbar">
        {!draft && <>
          <button className="button button-secondary button-icon" title={t("Read again")} aria-label={t("Read again")} onClick={refresh}><RefreshCw size={16} /></button>
          <button className="button button-secondary" onClick={() => setExporting(true)} disabled={Boolean(busy)}><Download size={15} /> {busy === "pdf" ? t("Making…") : t("Download")}</button>
          {canEdit && me.public_links && <button className="button button-secondary" onClick={() => setSharing(true)} title={t("A link that opens the report as a web page, without signing in")}><Globe2 size={15} /> {t("Share")}</button>}
          {canEdit && <button className="button button-secondary" onClick={() => void sendNow()} disabled={Boolean(busy) || !saved.recipients.length} title={saved.recipients.length ? t("Make it now and send it to its recipients") : t("Add recipients in Settings first")}><Send size={15} /> {busy === "send" ? t("Sending…") : t("Send now")}</button>}
          {canEdit && <button className="button button-secondary" onClick={() => setSettings(true)}><Settings2 size={15} /> {t("Settings")}</button>}
          {canEdit && <button className="button button-primary" onClick={startEditing}><Pencil size={15} /> {t("Edit")}</button>}
        </>}
        {draft && <>
          <button className="button button-secondary" onClick={() => setSettings(true)}><Settings2 size={15} /> {t("Settings")}</button>
          <button className="button button-secondary" onClick={stopEditing}><X size={15} /> {t("Cancel")}</button>
          <button className="button button-primary" onClick={() => void save()} disabled={busy === "save"}><Save size={15} /> {busy === "save" ? t("Saving…") : t("Save")}</button>
        </>}
      </div>
    </div>
    {error && <ErrorBox text={error} />}
    {notice && !draft && <div className="notice notice-ok" role="status">{notice.text}{notice.run && <> <a href={pdfUrl(notice.run)} target="_blank" rel="noreferrer">{t("Open the PDF")}</a></>}</div>}
    {highlight && tab === "sent" && !draft && <div className="notice" role="status">{t("The PDF you were sent is highlighted below; the Report tab shows the same report read now.")}</div>}
    {!draft && <div className="tc-pages"><PageTabs label={t("Report and the PDFs it made")} tabs={tabs} href={(to) => `${window.location.pathname}${writeQuery({ tab: to as Tab })}`} navigate={(to) => { setTab(to as Tab); go({ tab: to as Tab }); }} /></div>}

    {tab === "sent" && !draft ? (runs ? <RunsTable runs={runs} highlight={highlight} /> : <Loading />) : <div className={`tc-report-layout${outline.length ? " tc-has-outline" : ""}`}>
      {outline.length > 0 && <Outline entries={outline} />}
      <div className="tc-report-main">
      <article className={`tc-report-paper${draft ? " tc-report-editing" : ""}`} aria-label={shown.name}>
        <header className="tc-report-cover">
          <span className="pc-overline"><FileText size={13} aria-hidden /> {t("Report")}</span>
          <h2>{shown.name}</h2>
          {shown.description && <p>{shown.description}</p>}
          <dl>
            <div><dt>{t("Period")}</dt><dd>{t("{start} to {end}", { start: formatDate(range.start, { dateStyle: "medium", timeStyle: "short" }), end: formatDate(range.end, { dateStyle: "medium", timeStyle: "short" }) })}</dd></div>
            <div><dt>{t("Schedule")}</dt><dd>{cadenceLabel(shown.schedule)}</dd></div>
            <div><dt>{t("Time zone")}</dt><dd>{timeZoneLabel(saved.zone)}</dd></div>
          </dl>
        </header>
        {!shown.sections.length && <div className="tc-empty-list tc-report-empty">
          <h3>{t("This report has no sections yet")}</h3>
          <p className="muted">{canEdit ? t("Add notes, charts, KPIs, tables and the period's events: the PDF lays them out in this order.") : t("An editor has not added sections yet.")}</p>
          {canEdit && !draft && <button className="button button-primary" onClick={startEditing}><Pencil size={15} /> {t("Edit")}</button>}
        </div>}
        <div className="tc-report-sections">
          {shown.sections.map((section, index) => <section key={section.section_id} className={`tc-report-section tc-report-is-${section.kind}${section.width === "half" ? " tc-half" : ""}`} data-section={section.section_id}>
            {draft && <div className="tc-report-tools">
              <span className="pc-overline">{t(SECTION_LABELS[section.kind])}</span>
              <button type="button" className="icon-button" aria-label={t("Move up")} title={t("Move up")} disabled={!index} onClick={() => setSections(moveSection(draft.sections, section.section_id, -1))}><ArrowUp size={14} /></button>
              <button type="button" className="icon-button" aria-label={t("Move down")} title={t("Move down")} disabled={index === draft.sections.length - 1} onClick={() => setSections(moveSection(draft.sections, section.section_id, 1))}><ArrowDown size={14} /></button>
              {(section.kind === "card" || section.kind === "events") && <button type="button" className="icon-button" aria-label={section.width === "half" ? t("Full width") : t("Half width")} title={section.width === "half" ? t("Full width") : t("Half width: two in a row sit side by side")}
                onClick={() => setSections(replaceSection(draft.sections, { ...section, width: section.width === "half" ? "full" : "half" }))}>{section.width === "half" ? <Rows3 size={14} /> : <Columns2 size={14} />}</button>}
              {section.kind !== "break" && <button type="button" className="icon-button" aria-label={t("Edit section")} title={t("Edit section")} onClick={() => (section.kind === "text" ? setWriting(section.section_id) : setEditing(section))}><Pencil size={14} /></button>}
              <button type="button" className="icon-button" aria-label={t("Add a cell below")} title={t("Add a cell below")} aria-expanded={adding === section.section_id} disabled={sectionsFull} onClick={() => setAdding(adding === section.section_id ? null : section.section_id)}><Plus size={14} /></button>
              <button type="button" className="icon-button danger" aria-label={t("Remove section")} title={t("Remove section")} onClick={() => setSections(draft.sections.filter((item) => item.section_id !== section.section_id))}><Trash2 size={14} /></button>
            </div>}
            {draft && section.kind === "text" && writing === section.section_id
              ? <TextCell section={section} onChange={(next) => setSections(replaceSection(draft.sections, next))} onDone={() => doneWriting(section)} />
              : <div className={draft && section.kind === "text" ? "tc-report-writable" : undefined} onDoubleClick={draft && section.kind === "text" ? () => setWriting(section.section_id) : undefined}
                  title={draft && section.kind === "text" ? t("Double-click to write") : undefined}>
                <SectionBody section={section} read={readOf(section)} source={source} tick={tick} editing={Boolean(draft)} reportId={reportId} canEdit={canEdit} />
              </div>}
            {draft && adding === section.section_id && <div className="tc-report-add tc-report-add-here" role="group" aria-label={t("Add a cell below")}>
              {ADD.map(({ kind, icon: Icon }) => <button key={kind} type="button" className="tc-report-add-button" onClick={() => add(kind, index + 1)}><Plus size={13} aria-hidden /><Icon size={16} aria-hidden /><b>{t(SECTION_LABELS[kind])}</b></button>)}
            </div>}
          </section>)}
        </div>
        {draft && <div className="tc-report-add" role="group" aria-label={t("Add a section")}>
          {ADD.map(({ kind, icon: Icon, hint }) => <button key={kind} type="button" className="tc-report-add-button" disabled={sectionsFull} onClick={() => add(kind)}><Plus size={13} aria-hidden /><Icon size={16} aria-hidden /><b>{t(SECTION_LABELS[kind])}</b><small>{t(hint)}</small></button>)}
          {sectionsFull && <small className="muted">{t("A report has at most {n} sections.", { n: MAX_SECTIONS })}</small>}
        </div>}
      </article>
      <footer className="tc-foot"><small>{draft ? t("Panels read with your own access while you edit; the PDF reads with View's.") : t("Read at {time} over {period}", { time: formatDate(stamp, { timeStyle: "medium" }), period: windowLabel(shown.period) })}</small></footer>
      </div>
    </div>}

    {exporting && <ExportDialog reportId={reportId} busy={Boolean(busy)} onClose={() => setExporting(false)} onPdf={() => { setExporting(false); void makePdf(); }} />}
    {sharing && <ShareDialog target="report" dashboardId={reportId} name={saved.name} isAdmin={me.is_admin} onClose={() => setSharing(false)} />}
    {editing?.kind === "assistant" && <AssistantDialog section={editing} onClose={() => { setEditing(null); setInsertAt(null); }} onSave={applySection} />}
    {editing?.kind === "alarms" && <AlarmsDialog section={editing} onClose={() => { setEditing(null); setInsertAt(null); }} onSave={applySection} />}
    {editing?.kind === "events" && <EventsDialog section={editing} onClose={() => { setEditing(null); setInsertAt(null); }} onSave={applySection} />}
    {editing?.kind === "card" && editing.card && draft && <CardEditor initial={editing.card} isNew={!draft.sections.some((item) => item.section_id === editing.section_id)} period={draft.period}
      onClose={() => { setEditing(null); setInsertAt(null); }} onSave={(card) => applySection({ ...editing, card })} />}
    {settings && <ReportSettingsDialog draft={draft ?? reportDraftOf(saved)} folders={folders} zone={saved.zone} onClose={() => setSettings(false)} onApply={(next) => void applySettings(next)} />}
  </div>;
}
