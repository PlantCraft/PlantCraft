import { DataTable, Dialog, type DataColumn, formatDate, useAssistantPage } from "@plantcraft/ui";
import { BellOff, Check, CheckCheck, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api } from "./api";
import { formatAgo, t } from "./i18n";
import { navigate } from "./nav";
import type { Alarm, Me, Summary } from "./types";
import { ErrorBox, Heading, Link, Loading, PRIORITY_WORDS, PriorityPill, STATUS_WORDS, StatusPill, message, reading } from "./ui";

const REFRESH_MS = 5_000;
const SCOPE_KEY = "alarmcraft.alarms.mine";

export const SHELVE_CHOICES = [15, 60, 240, 480, 1440, 10080];

function shelveLabel(minutes: number): string {
  if (minutes < 60) return t("{n} min", { n: minutes });
  if (minutes < 1440) return t("{n} h", { n: minutes / 60 });
  return minutes === 10080 ? t("7 days") : t("{n} h", { n: minutes / 60 });
}

/** Shelve one alarm: a duration and a reason (ISA-18.2 shelving). */
export function ShelveDialog({ alarm, onClose, onDone }: { alarm: Alarm; onClose: () => void; onDone: () => void }) {
  const [minutes, setMinutes] = useState(60);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  async function shelve() {
    try {
      await api.shelve(alarm.alarm_id, minutes, reason);
      onDone();
    } catch (err) {
      setError(message(err));
    }
  }
  return <Dialog title={t("Shelve {name}", { name: alarm.name })} onClose={onClose} initialFocus="input" footer={<>
    <button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button>
    <button type="button" className="button button-primary" disabled={!reason.trim()} onClick={() => void shelve()}><BellOff size={16} />{t("Shelve")}</button>
  </>}>
      <p className="muted">{t("A shelved alarm raises nothing until the time ends. If it is still active then, it is announced again.")}</p>
      <div className="form-grid">
        <label>{t("For")}
          <select value={minutes} onChange={(event) => setMinutes(Number(event.target.value))}>
            {SHELVE_CHOICES.map((value) => <option key={value} value={value}>{shelveLabel(value)}</option>)}
          </select>
        </label>
        <label className="field-span">{t("Why")}
          <input value={reason} maxLength={500} onChange={(event) => setReason(event.target.value)} placeholder={t("Instrument under maintenance")} />
        </label>
      </div>
      {error && <ErrorBox text={error} />}
  </Dialog>;
}

/** What the operator can do on one alarm: acknowledge, shelve, unshelve. */
export function AlarmActions({ alarm, me, onChanged, onShelve }: { alarm: Alarm; me: Me; onChanged: () => void; onShelve: (alarm: Alarm) => void }) {
  const [busy, setBusy] = useState(false);
  async function act(run: () => Promise<unknown>) {
    setBusy(true);
    try { await run(); } finally { setBusy(false); onChanged(); }
  }
  if (!me.can_edit) return null;
  return <>
    {!alarm.acked && <button type="button" className="button button-small button-primary" disabled={busy} onClick={() => void act(() => api.ack(alarm.alarm_id))}><Check size={14} />{t("Acknowledge")}</button>}
    {alarm.status !== "shelved" && <button type="button" className="button button-small button-secondary" disabled={busy} onClick={() => onShelve(alarm)}><BellOff size={14} />{t("Shelve")}</button>}
    {alarm.status === "shelved" && <button type="button" className="button button-small button-secondary" disabled={busy} onClick={() => void act(() => api.unshelve(alarm.alarm_id))}>{t("Unshelve")}</button>}
  </>;
}

const RANK: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
const labelled = (words: Record<string, string>) => Object.entries(words).map(([value, label]) => ({ value, label: t(label) }));

/** What an alarm is about, in one line: its asset or execution, or the value its rule reads. */
export function aboutWords(alarm: Alarm): string {
  if (alarm.label) return alarm.label;
  if (alarm.asset_id) return alarm.asset_id;
  if (alarm.subject.startsWith("execution:")) return alarm.subject.split(":").slice(2).join(":");
  return alarm.signal ?? "";
}

/** An alarm list: priority, state, the alarm and what it is about, its value, when it was last
 * raised, and the operator's actions. A row opens the alarm. */
export function AlarmTable({ alarms, me, onChanged, searchable = true, toolbar, selectable = false, empty }: {
  alarms: Alarm[]; me: Me; onChanged: () => void; searchable?: boolean; toolbar?: ReactNode; selectable?: boolean; empty?: ReactNode;
}) {
  const [shelving, setShelving] = useState<Alarm | null>(null);
  const columns: DataColumn<Alarm>[] = [
    { key: "priority", label: t("Priority"), phone: "hide", sort: (alarm) => RANK[alarm.priority] ?? 9, filter: searchable ? { options: labelled(PRIORITY_WORDS), value: (alarm) => alarm.priority } : undefined, render: (alarm) => <PriorityPill priority={alarm.priority} /> },
    { key: "status", label: t("State"), phone: "hide", sort: (alarm) => STATE_RANK[alarm.status] ?? 9, filter: searchable ? { options: labelled(STATUS_WORDS), value: (alarm) => alarm.status } : undefined, render: (alarm) => <StatusPill status={alarm.status} /> },
    { key: "name", label: t("Alarm"), className: "al-name", sort: (alarm) => alarm.name, render: (alarm) => <>
      <Link to={`/alarms/${alarm.alarm_id}`} className="strong">{alarm.name}</Link>
      {/* A phone leaves out the Priority and State columns: both show here, under the name. */}
      <div className="al-phone-pills"><PriorityPill priority={alarm.priority} /> <StatusPill status={alarm.status} /></div>
      <div className="small muted">{[aboutWords(alarm), alarm.status === "shelved" ? t("shelved until {when}", { when: formatDate(alarm.shelved_until) }) : ""].filter(Boolean).join(" · ")}</div>
    </> },
    { key: "area", label: t("Area"), className: "small", phone: "hide", sort: (alarm) => alarm.area_name ?? "", filter: searchable ? { value: (alarm) => alarm.area_name ?? t("No area") } : undefined, render: (alarm) => alarm.area_name ?? "–" },
    { key: "value", label: t("Value"), numeric: true, className: "nowrap", sort: (alarm) => (typeof alarm.value === "number" ? alarm.value : null), render: (alarm) => (alarm.value === null ? "–" : reading(alarm.value, alarm.unit)) },
    { key: "raised", label: t("Last raised"), className: "nowrap small", phone: "hide", sort: (alarm) => alarm.raised_at, render: (alarm) => (alarm.raised_at ? formatAgo(alarm.raised_at) : "–") },
    { key: "actions", label: <span className="sr-only">{t("Actions")}</span>, className: "row-actions", phone: "hide", render: (alarm) => <AlarmActions alarm={alarm} me={me} onChanged={onChanged} onShelve={setShelving} /> },
  ];
  return <>
    <DataTable rows={alarms} columns={columns} rowKey={(alarm) => alarm.alarm_id} rowClassName={(alarm) => `al-row al-row-${alarm.status} al-priority-${alarm.priority}`} label={t("Alarms")} className="al-table"
      onRowClick={(alarm) => navigate(`/alarms/${alarm.alarm_id}`)} toolbar={toolbar} empty={empty}
      initialSort={searchable ? { key: "status", descending: false } : undefined}
      selectable={selectable && me.can_edit}
      actions={selectable && me.can_edit ? (rows, clear) => {
        const open = rows.filter((alarm) => !alarm.acked).map((alarm) => alarm.alarm_id);
        return <button type="button" className="button button-small button-primary" disabled={!open.length} onClick={() => void api.ackAll(open).then(() => { clear(); onChanged(); })}><CheckCheck size={14} />{t("Acknowledge ({count})", { count: open.length })}</button>;
      } : undefined}
      searchText={searchable ? (alarm) => `${alarm.name} ${alarm.signal ?? ""} ${alarm.asset_id ?? ""} ${alarm.area_name ?? ""} ${alarm.rule_name ?? ""}` : undefined} searchPlaceholder={t("Search alarms, signals or assets")} />
    {shelving && <ShelveDialog alarm={shelving} onClose={() => setShelving(null)} onDone={() => { setShelving(null); onChanged(); }} />}
  </>;
}

/** Most urgent state first: unacknowledged, returned unacknowledged, acknowledged, shelved, out of service, normal. */
const STATE_RANK: Record<string, number> = { unacked: 0, rtn_unacked: 1, acked: 2, shelved: 3, out_of_service: 4, normal: 5 };

type Show = "attention" | "unacked" | "all";
const SHOW_KEY = "alarmcraft.alarms.show";
const SHOW_WORDS: Record<Show, string> = { attention: "Needs attention", unacked: "Unacknowledged", all: "All" };

function saved<T extends string>(key: string, fallback: T, allowed: readonly T[]): T {
  try { const value = window.localStorage.getItem(key) as T | null; return value && allowed.includes(value) ? value : fallback; } catch { return fallback; }
}
function keep(key: string, value: string) {
  try { window.localStorage.setItem(key, value); } catch { /* private window */ }
}

/** Alarms: every alarm, one table. "Needs attention" (the default) keeps those active,
 * unacknowledged or shelved; "Unacknowledged" those still to acknowledge; "All" every alarm
 * the rules made. "Only mine" keeps those the person answers for or is notified about.
 * ``?rule=<id>`` keeps one rule's. Refreshed every 5 seconds. */
export function SummaryPage({ me, rule }: { me: Me; rule?: string }) {
  const [alarms, setAlarms] = useState<Alarm[] | null>(null);
  const [monitor, setMonitor] = useState<Summary["monitor"] | null>(null);
  const [error, setError] = useState("");
  const [show, setShow] = useState<Show>(() => saved(SHOW_KEY, "attention", ["attention", "unacked", "all"]));
  const [mine, setMine] = useState(() => saved<"1" | "0">(SCOPE_KEY, "0", ["1", "0"]) === "1");
  const load = useCallback(() => Promise.all([api.alarms(), api.summary(rule)])
    .then(([all, summary]) => { setAlarms(rule ? all.filter((alarm) => alarm.rule_id === rule) : all); setMonitor(summary.monitor); setError(""); })
    .catch((err) => setError(message(err))), [rule]);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [load]);
  const attention = (alarm: Alarm) => alarm.active || !alarm.acked || alarm.status === "shelved";
  const shown = (alarms ?? []).filter((alarm) => (show === "all" ? true : show === "unacked" ? !alarm.acked && alarm.status !== "normal" && alarm.status !== "out_of_service" : attention(alarm) && alarm.status !== "normal" && alarm.status !== "out_of_service"))
    .filter((alarm) => !mine || alarm.mine);
  // Alarms' works here (app.toml): which alarms first.
  useAssistantPage(alarms && { place: t("Alarms"), page: "alarmcraft:active", facts: { shown: shown.length, all: alarms.length, show },
    view: { rule: rule ?? "", alarms: shown.slice(0, 30).map((item) => `${item.priority_label} ${item.name} (${item.alarm_id}): ${item.condition}, ${item.acked ? "acknowledged" : "not acknowledged"}, since ${item.raised_at ?? "?"}`) } });
  if (!alarms) return error ? <ErrorBox text={error} /> : <Loading />;
  const choose = (value: Show) => { setShow(value); keep(SHOW_KEY, value); };
  const toolbar = <>
    <div className="pc-segmented" role="group" aria-label={t("Which alarms")}>
      {(Object.keys(SHOW_WORDS) as Show[]).map((value) => <button key={value} type="button" className={show === value ? "on" : ""} aria-pressed={show === value} onClick={() => choose(value)}>{t(SHOW_WORDS[value])}</button>)}
    </div>
    <label className="al-check"><input type="checkbox" checked={mine} onChange={(event) => { setMine(event.target.checked); keep(SCOPE_KEY, event.target.checked ? "1" : "0"); }} />{t("Only mine")}</label>
  </>;
  return <>
    <Heading title={t("Alarms")} detail={t("Every alarm the rules made, most urgent first. Open one for its value, its history and what was sent.")}
      actions={me.can_edit && !me.demo && <button type="button" className="button button-icon" title={t("Evaluate the rules now")} aria-label={t("Evaluate now")}
        onClick={() => { api.run().then(() => load()).catch((err) => setError(message(err))); }}><RefreshCw size={16} /></button>} />
    {error && <ErrorBox text={error} />}
    {monitor?.last_error && <div className="notice notice-error">{monitor.last_error}</div>}
    {rule && <div className="notice">{t("Only the alarms of one rule.")} <Link to={`/rules/${rule}`}>{t("Open the rule")}</Link> · <Link to="/alarms">{t("Show every rule")}</Link></div>}
    <AlarmTable alarms={shown} me={me} onChanged={() => void load()} toolbar={toolbar} selectable
      empty={<p className="muted al-pad">{alarms.length ? (show === "all" ? t("No alarm matches.") : t("No alarm needs attention.")) : t("No alarms yet: create a rule in Rules, or from an event in Events.")}</p>} />
  </>;
}
