import { appLabel, DataTable, useAssistantPage } from "@plantcraft/ui";
import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { formatAgo, formatDate, t } from "./i18n";
import { navigate } from "./nav";
import type { Condition, IncomingEvent, Me } from "./types";
import { ErrorBox, Heading, Link, Loading, Pill, WindowPicker, message } from "./ui";

export const SEVERITY_WORDS: Record<string, string> = { info: "Info", ok: "OK", warning: "Warning", critical: "Critical", "": "None" };
export const SEVERITY_PILL: Record<string, string> = { ok: "ok", warning: "warning", critical: "alarm" };
const STATE_WORDS: Record<string, string> = { open: "Open", ended: "Ended", instant: "Instant" };
const labelled = (words: Record<string, string>) => Object.entries(words).map(([value, label]) => ({ value, label: t(label) }));

/** One line of the table: an event the apps reported, or a condition still open. */
interface Row {
  id: string; event?: number; at: string; app: string; kind: string; subject: string; summary: string; severity: string;
  state: "open" | "ended" | "instant"; rules: string[]; rule_names: string[]; key: string;
}

/** "FIC-1001", "Execution daily-loops": what an event is about, without the prefix. */
export function aboutWords(subject: string): string {
  const [kind, ...rest] = subject.split(":");
  const value = rest.join(":");
  if (!value) return subject || "–";
  if (kind === "asset") return value;
  return `${t(kind === "schedule" || kind === "execution" ? "Execution" : kind)} ${value}`;
}

/** The newest event of each condition still open is "open"; its start ended is "ended". */
function rowsOf(events: IncomingEvent[], open: Condition[]): Row[] {
  const openKeys = new Set(open.map((item) => `${item.app}|${item.key}`));
  return events.map((event) => ({
    id: String(event.id), event: event.id, at: event.at, app: event.app, kind: event.kind, subject: event.subject, summary: event.summary, severity: event.severity,
    state: !event.phase || event.phase === "instant" ? "instant" : event.phase === "start" && event.key && openKeys.has(`${event.app}|${event.key}`) ? "open" : "ended",
    rules: event.rules, rule_names: event.rule_names ?? event.rules, key: event.key ?? "",
  }));
}

/** Conditions open before the period: still listed under "Open now". */
function openRows(open: Condition[], rows: Row[]): Row[] {
  const seen = new Set(rows.filter((row) => row.state === "open").map((row) => `${row.app}|${row.kind}|${row.subject}`));
  return open.filter((item) => !seen.has(`${item.app}|${item.kind}|${item.subject}`)).map((item) => ({
    id: `open:${item.app}|${item.key}`, at: item.opened_at, app: item.app, kind: item.kind, subject: item.subject, summary: item.summary, severity: item.severity,
    state: "open", rules: [], rule_names: [], key: item.key,
  }));
}

type Show = "open" | "all";

/** Events: what the other apps of the suite reported (changes only), in one table. "Open now"
 * (the default) keeps the conditions started and not ended (an execution failing, a signal
 * without data); "All" every event of the period. A row opens the event's page (where it came
 * from), where a rule can start. Events notify nobody on their own: a rule decides when one
 * becomes an alarm. */
export function EventsPage({ me }: { me: Me }) {
  const [period, setPeriod] = useState("24h");
  const [show, setShow] = useState<Show>("open");
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState("");
  // The apps' own titles for their event kinds (their catalog), so a row reads "Signal without
  // data", not "histcraft.point.no_data"; the kind stays on the event's page.
  const [titles, setTitles] = useState<Record<string, string>>({});
  useEffect(() => {
    void api.catalog().then((catalog) => setTitles(Object.fromEntries(catalog.apps.flatMap((app) => app.events.filter((item) => item.title).map((item) => [item.kind, item.title]))))).catch(() => undefined);
  }, []);
  const kindWords = (kind: string) => titles[kind] || kind;
  const load = useCallback(() => Promise.all([api.incoming({ window: period }), api.conditions()])
    .then(([incoming, open]) => {
      const received = rowsOf(incoming.events, open);
      setRows([...openRows(open, received), ...received]);
      setError(incoming.error ? t("Reading the events failed: {why}", { why: incoming.error }) : !incoming.service_key ? t("Alarms has no app key yet: it cannot read what the apps report. An administrator sets it in PlantCraft (Apps).") : "");
    })
    .catch((err) => setError(message(err))), [period]);
  useEffect(() => { setRows(null); void load(); }, [load]);
  const shown = (rows ?? []).filter((row) => show === "all" || row.state === "open");
  useAssistantPage(rows && { place: t("Alarms › Events"), page: "alarmcraft:events", facts: { shown: shown.length, show, period },
    view: { events: shown.slice(0, 40).map((row) => `${row.at} ${row.app} ${row.kind} ${row.subject} ${row.severity} ${row.state}: ${row.summary}`) } });
  const open = (row: Row) => (row.event ? `/events/${row.event}` : `/events/open?app=${encodeURIComponent(row.app)}&key=${encodeURIComponent(row.key)}`);
  const toolbar = <>
    <div className="pc-segmented" role="group" aria-label={t("Which events")}>
      <button type="button" className={show === "open" ? "on" : ""} aria-pressed={show === "open"} onClick={() => setShow("open")}>{t("Open now")}</button>
      <button type="button" className={show === "all" ? "on" : ""} aria-pressed={show === "all"} onClick={() => setShow("all")}>{t("All")}</button>
    </div>
    {show === "all" && <WindowPicker value={period} onChange={setPeriod} options={["24h", "7d", "30d"]} />}
  </>;
  return <>
    <Heading title={t("Events")}
      actions={<button type="button" className="button button-icon" title={t("Refresh")} aria-label={t("Refresh")} onClick={() => void load()}><RefreshCw size={16} /></button>} />
    {error && <div className="notice notice-error">{error}</div>}
    {!rows ? <Loading /> : <DataTable rows={shown} rowKey={(row) => row.id} label={t("Events")} initialSort={{ key: "at", descending: true }} toolbar={toolbar}
      onRowClick={(row) => navigate(open(row))}
      searchText={(row) => `${row.kind} ${kindWords(row.kind)} ${row.subject} ${row.summary} ${appLabel(row.app, row.app)}`} searchPlaceholder={t("Search events, assets or summaries")}
      empty={<p className="muted al-pad">{show === "open" ? t("Nothing is open: no app has a condition started and not ended.") : t("Nothing came in during this period.")}</p>}
      columns={[
        { key: "kind", label: t("Event"), className: "al-wrap", sort: (row) => kindWords(row.kind), filter: { value: (row) => kindWords(row.kind), label: t("Type") }, render: (row) => <><b title={row.kind}>{kindWords(row.kind)}</b><div className="small muted">{row.summary}</div></> },
        { key: "app", label: t("App"), className: "small", sort: (row) => appLabel(row.app, row.app), filter: { value: (row) => appLabel(row.app, row.app) }, render: (row) => appLabel(row.app, row.app) },
        { key: "subject", label: t("About"), className: "small al-wrap", sort: (row) => aboutWords(row.subject), filter: { value: (row) => aboutWords(row.subject) }, render: (row) => aboutWords(row.subject) },
        { key: "severity", label: t("Severity"), className: "small", sort: (row) => row.severity, filter: { options: labelled(SEVERITY_WORDS), value: (row) => row.severity }, render: (row) => (row.severity ? <Pill status={SEVERITY_PILL[row.severity] ?? "unknown"} label={t(SEVERITY_WORDS[row.severity] ?? row.severity)} /> : "–") },
        { key: "state", label: t("State"), className: "small", sort: (row) => row.state, filter: { options: labelled(STATE_WORDS), value: (row) => row.state }, render: (row) => t(STATE_WORDS[row.state]) },
        { key: "at", label: t("When"), className: "small nowrap", sort: (row) => row.at, render: (row) => <span title={formatDate(row.at)}>{formatAgo(row.at)}</span> },
        { key: "rules", label: t("Rules"), className: "small", filter: { value: (row) => (row.rules.length ? t("A rule") : t("No rule")), label: t("Counted") }, render: (row) => (row.rules.length ? row.rules.map((rule, index) => <div key={rule}><Link to={`/rules/${rule}`}>{row.rule_names[index] ?? rule}</Link></div>) : <span className="muted">–</span>) },
      ]} />}
  </>;
}
