import { DataTable, FollowUp, useAssistantPage } from "@plantcraft/ui";
import { Pencil, Power } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "./api";
import { AlarmChart } from "./AlarmChart";
import { formatAgo, formatDate, t } from "./i18n";
import { JournalTable } from "./JournalTable";
import { AlarmActions, ShelveDialog } from "./SummaryPage";
import { useDirectory, whoLabel } from "./people";
import type { Alarm, AlarmHistory, Me, Sent } from "./types";
import { ErrorBox, Heading, Link, Loading, PriorityPill, StatusPill, WindowPicker, message, reading } from "./ui";

const SENT_WORDS: Record<string, string> = { raised: "Raised", cleared: "Cleared", reminder: "Reminder", escalation: "Escalation" };
const OUTBOX_WORDS: Record<string, string> = { pending: "Waiting", sent: "Sent", dropped: "Not sent" };

/** What an alarm is about: its asset or execution, or its rule's named values. */
export function subjectWords(alarm: Alarm): string {
  if (alarm.label) return alarm.label;
  if (alarm.asset_id) return alarm.asset_id;
  if (alarm.subject.startsWith("execution:")) return alarm.subject.split(":").slice(2).join(":");
  return alarm.signal ?? t("the values its rule names");
}

/** One alarm: its state and actions, what it is about, its value with the limit and occurrences
 * (or the events that raised it), its history and the messages sent about it. ``ack``: opened
 * from a message's Acknowledge. */
export function AlarmPage({ alarmId, me, ack = false }: { alarmId: string; me: Me; ack?: boolean }) {
  const [period, setPeriod] = useState("24h");
  const [data, setData] = useState<AlarmHistory | null>(null);
  const [error, setError] = useState("");
  const [sent, setSent] = useState<Sent["outbox"] | null>(null);
  const [shelving, setShelving] = useState<Alarm | null>(null);
  const directory = useDirectory();
  useEffect(() => { api.sent().then((value) => setSent(value.outbox)).catch(() => setSent([])); }, [alarmId]);
  const load = useCallback(() => api.history(alarmId, period).then(setData).catch((err) => setError(message(err))), [alarmId, period]);
  useEffect(() => { void load(); }, [load]);
  // Acknowledge from a message (``?ack=1``): once, then the address loses the ``ack``.
  const acked = useRef(false);
  const [ackNote, setAckNote] = useState("");
  useEffect(() => {
    if (!ack || acked.current || !data) return;
    acked.current = true;
    try { window.history.replaceState({}, "", window.location.pathname); } catch { /* old browser */ }
    if (data.alarm.acked) { setAckNote(t("Already acknowledged by {who}.", { who: data.alarm.acked_by ?? "" })); return; }
    if (!me.can_edit) { setAckNote(t("Your access to Alarms is read-only: you cannot acknowledge.")); return; }
    void api.ack(alarmId).then(() => { setAckNote(t("Acknowledged.")); void load(); }).catch((err) => setError(message(err)));
  }, [ack, data, me.can_edit, alarmId, load]);
  // What the assistant can do on this page (the button at the top opens it).
  const source = data ? subjectWords(data.alarm) : "";
  // Alarms' work (app.toml: why it fired), PlantCraft's "create an action" it offers here, and
  // the page's own tasks.
  useAssistantPage(data && {
    page: "alarmcraft:alarm",
    facts: { alarm: data.alarm.alarm_id, condition: data.alarm.condition, priority: data.alarm.priority_label, status: data.alarm.status, value: data.alarm.signal ?? "",
      occurrences: data.occurrences.length, period, last: data.occurrences.map((item) => item.started_at ?? item.start ?? "").sort().pop() ?? "" },
    subject: data.alarm.asset_id ? `asset:${data.alarm.asset_id}` : data.alarm.signal ? `signal:${data.alarm.signal}` : undefined,
    title: data.alarm.name,
    place: t("Alarms › {name}", { name: data.alarm.name }),
    context: [`Alarm ${data.alarm.name} (${data.alarm.alarm_id}): when ${data.alarm.condition}, priority ${data.alarm.priority_label}, status ${data.alarm.status}.`,
      `About: ${source}.`, data.alarm.signal ? `Value read: ${data.alarm.signal}.` : "", data.alarm.message ? `The rule said: ${data.alarm.message}.` : "", `Raised ${data.occurrences.length} times in the last ${period}.`,
      data.alarm.cause ? `Cause: ${data.alarm.cause}.` : "", data.alarm.consequence ? `Consequence: ${data.alarm.consequence}.` : "", data.alarm.action ? `Corrective action: ${data.alarm.action}.` : ""].filter(Boolean).join("\n"),
  });
  if (!data) return error ? <ErrorBox text={error} /> : <Loading />;
  const { alarm } = data;
  const inService = alarm.status !== "out_of_service";
  const events = alarm.hears.length > 0;
  const values = Boolean(alarm.signal) || data.chart.t.length > 0;
  const facts: Array<[string, ReactNode]> = [
    [t("State"), <><StatusPill status={alarm.status} /> <PriorityPill priority={alarm.priority} /></>],
    [t("When"), alarm.condition],
    [t("About"), source || "–"],
    ...(values ? [[t("Last value"), <>{alarm.value === null ? "–" : reading(alarm.value, alarm.unit)}{alarm.value_at ? <span className="muted"> · {formatAgo(alarm.value_at)}</span> : null}</>] as [string, ReactNode]] : []),
    ...(alarm.rule_id ? [[t("Rule"), <Link to={`/rules/${alarm.rule_id}`}>{alarm.rule_name ?? alarm.rule_id}</Link>] as [string, ReactNode]] : []),
    [t("Owner"), whoLabel(alarm.owner, directory)],
    ...(alarm.message ? [[t("Message"), alarm.message] as [string, ReactNode]] : []),
    ...(events && alarm.last_summary ? [[t("Last event"), alarm.last_summary] as [string, ReactNode]] : []),
    ...(alarm.members_active.length ? [[t("Active on"), alarm.members_active.join(", ")] as [string, ReactNode]] : []),
    ...(alarm.reason ? [[t("Note"), alarm.reason] as [string, ReactNode]] : []),
    ...(alarm.status === "shelved" ? [[t("Shelved"), t("by {who} until {when}: {why}", { who: alarm.shelved_by ?? "", when: formatDate(alarm.shelved_until), why: alarm.shelve_reason ?? "" })] as [string, ReactNode]] : []),
    ...(alarm.action ? [[t("Corrective action"), alarm.action] as [string, ReactNode]] : []),
  ];
  const mine = sent?.filter((row) => row.alarm_id === alarm.alarm_id) ?? null;
  return <>
    <Heading eyebrow={<Link to="/alarms">{t("Alarms")}</Link>} title={alarm.name}
      actions={<>
        <AlarmActions alarm={alarm} me={me} onChanged={() => void load()} onShelve={setShelving} heading />
        {me.can_edit && <>
          <button type="button" className="button button-secondary" onClick={() => void api.enable(alarm.alarm_id, !inService).then(load).catch((err) => setError(message(err)))}>
            <Power size={16} />{inService ? t("Take out of service") : t("Return to service")}
          </button>
          {alarm.rule_id && <Link to={`/rules/${alarm.rule_id}/edit`} className="button button-secondary"><Pencil size={16} />{t("Change the rule")}</Link>}
        </>}
      </>} />
    {error && <ErrorBox text={error} />}
    {ackNote && <div className="notice notice-ok">{ackNote}</div>}
    <section className="panel"><dl className="al-facts">{facts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl></section>
    {values && <section className="panel">
      <div className="panel-header"><div><h2>{t("Value")}</h2><p>{alarm.signal ?? ""}</p></div><WindowPicker value={period} options={["6h", "24h", "7d"]} onChange={setPeriod} /></div>
      {data.problem && <div className="notice">{data.problem}</div>}
      <AlarmChart chart={data.chart} occurrences={data.occurrences} end={data.end} unit={alarm.unit} />
    </section>}
    {events && <section className="panel table-panel">
      <div className="panel-header al-pad"><div><h2>{t("Events")}</h2><p>{t("What the apps reported about {subject}, and which events counted.", { subject: source })}</p></div>{!values && <WindowPicker value={period} options={["24h", "7d", "30d"]} onChange={setPeriod} />}</div>
      {data.events?.length ? <DataTable rows={data.events} rowKey={(event) => String(event.id)} label={t("Events")} initialSort={{ key: "at", descending: true }} columns={[
        { key: "at", label: t("When"), className: "small nowrap", sort: (event) => event.at, render: (event) => formatDate(event.at) },
        { key: "kind", label: t("Event"), sort: (event) => event.kind, render: (event) => <><b>{event.kind}</b><div className="small muted">{event.summary}</div></> },
        { key: "counted", label: t("Counted"), className: "small", sort: (event) => (event.counted ? 0 : 1), render: (event) => (event.counted ? t("Yes") : t("No")) },
      ]} /> : <p className="muted al-pad">{t("No event in this period.")}</p>}
    </section>}
    <h2 className="section-title">{t("History")}</h2>
    {data.journal.length ? <JournalTable rows={data.journal} showName={false} /> : <p className="muted">{t("Nothing yet.")}</p>}
    <h2 className="section-title">{t("Messages sent")}</h2>
    {!mine ? <Loading /> : mine.length ? <DataTable rows={mine} rowKey={(row) => String(row.id)} label={t("Messages sent")} initialSort={{ key: "at", descending: true }} columns={[
      { key: "at", label: t("When"), className: "small nowrap", sort: (row) => row.at, render: (row) => formatDate(row.at) },
      { key: "what", label: t("Message"), render: (row) => <>{t(SENT_WORDS[row.event] ?? row.event)}{row.step ? ` ${row.step}` : ""}{row.detail ? <div className="small muted">{row.detail}</div> : null}</> },
      { key: "to", label: t("To"), className: "small", render: (row) => row.recipients.map((ref) => whoLabel(ref, directory)).join(", ") },
      { key: "status", label: t("State"), className: "small", sort: (row) => row.status, render: (row) => <>{t(OUTBOX_WORDS[row.status] ?? row.status)}{row.error && <div className="muted">{row.error}</div>}</> },
    ]} /> : <p className="muted">{alarm.notify ? t("Nothing sent yet.") : t("Its rule sends no messages: this alarm shows in Alarms only.")}</p>}
    {alarm.asset_id && <FollowUp subject={`asset:${alarm.asset_id}`} newTitle={`${alarm.name}: ${alarm.cause || t("review the alarm")}`} platformUrl={me.processcraft_url} canCreate={me.can_edit}
      detail={t("What was decided about this asset, in PlantCraft: an instrument to check, a limit to review.")} />}
    {shelving && <ShelveDialog alarm={shelving} onClose={() => setShelving(null)} onDone={() => { setShelving(null); void load(); }} />}
  </>;
}
