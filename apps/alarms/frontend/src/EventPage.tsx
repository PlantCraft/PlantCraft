import { appLabel, DataTable, useAssistantPage } from "@plantcraft/ui";
import { ExternalLink, Plus } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "./api";
import { formatAgo, formatDate, t } from "./i18n";
import { navigate } from "./nav";
import type { EventDetail, Me } from "./types";
import { ErrorBox, Heading, Link, Loading, Pill, message } from "./ui";
import { aboutWords, SEVERITY_PILL, SEVERITY_WORDS } from "./EventsPage";

const PHASE_WORDS: Record<string, string> = { start: "Started", end: "Ended", instant: "Happened" };
/** What a reference of the event is, as the platform names it (`GET /api/refs`). */
interface Resolved { title?: string; href?: string | null; kind_label?: string; exists?: boolean }

/** The references the event names (the asset, the run behind it), named and linked by PlantCraft.
 * Read from the platform with the person's own session, so only what they may see is named. */
function useRefs(refs: string[]): Record<string, Resolved> {
  const [found, setFound] = useState<Record<string, Resolved>>({});
  const wanted = refs.join("\n");
  useEffect(() => {
    if (!wanted) return;
    const search = new URLSearchParams();
    for (const ref of wanted.split("\n")) search.append("ref", ref);
    fetch(`/api/refs?${search}`, { credentials: "same-origin" })
      .then((answer) => (answer.ok ? answer.json() : {}))
      .then((value: unknown) => setFound(value && typeof value === "object" ? value as Record<string, Resolved> : {}))
      .catch(() => setFound({}));
  }, [wanted]);
  return found;
}

/** "run:linkcraft/42" → "Run" (when the platform does not name it). */
function refKind(ref: string): string {
  const kind = ref.split(":")[0];
  return t({ asset: "Asset", run: "Run", signal: "Signal", schedule: "Execution", execution: "Execution" }[kind] ?? kind);
}

/** A value the app sent, as text. */
function shown(value: unknown): string {
  if (value === null || value === undefined || value === "") return "–";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** One event (owner's review, 2026-10-27): clicking an event opens what it is and where it came
 * from (the app, the asset, the run behind it, what the app sent, the same condition's earlier
 * starts and ends), before any rule. A rule starts from here, when one is wanted. */
export function EventPage({ eventId, condition, me }: { eventId?: number; condition?: { app: string; key: string }; me: Me }) {
  const [detail, setDetail] = useState<EventDetail | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const load = eventId ? api.event(eventId) : condition ? api.condition(condition.app, condition.key) : Promise.reject(new Error(t("Event not found.")));
    load.then(setDetail).catch((err) => setError(message(err)));
  }, [eventId, condition?.app, condition?.key]);
  const event = detail?.event;
  const refs = useRefs(event ? [...new Set([event.subject, ...(event.refs ?? [])].filter((ref) => ref.includes(":")))] : []);
  useAssistantPage(event ? { page: "alarmcraft:event", title: event.kind, place: t("Alarms › Event {kind}", { kind: event.kind }),
    facts: { kind: event.kind, app: event.app, about: event.subject, severity: event.severity, at: event.at, summary: event.summary, open: detail?.open ?? false, refs: event.refs ?? [] } } : null);
  if (!detail || !event) return error ? <ErrorBox text={error} /> : <Loading />;
  const declared = detail.declared;
  const state = event.phase === "start" ? (detail.open ? t("Open") : t("Ended")) : event.phase === "end" ? t("Ended") : t("Instant");
  const url = typeof event.payload?.url === "string" && event.payload.url.startsWith("/") ? event.payload.url : "";
  const appName = declared?.app_name && declared.app_name !== event.app ? declared.app_name : appLabel(event.app, event.app);
  const sent = Object.entries(event.payload ?? {}).filter(([key]) => key !== "url");
  const asset = event.subject.startsWith("asset:") ? event.subject.slice(6) : "";
  const newRule = event.id ? `/rules/new?from=${event.id}` : `/rules/new?kind=${encodeURIComponent(event.kind)}`;
  const facts: Array<[string, ReactNode]> = [
    [t("Event type"), <code>{event.kind}</code>],
    [t("From"), appName],
    [t("About"), asset ? <Link to={`/assets/${encodeURIComponent(asset)}`}>{aboutWords(event.subject)}</Link> : aboutWords(event.subject)],
    [t("Severity"), event.severity ? <Pill status={SEVERITY_PILL[event.severity] ?? "unknown"} label={t(SEVERITY_WORDS[event.severity] ?? event.severity)} /> : "–"],
    [t("State"), state],
    [t("When"), <span title={formatAgo(event.at)}>{formatDate(event.at)}</span>],
  ];
  const linked = Object.entries(refs).filter(([ref, item]) => ref !== event.subject && item?.href);
  return <>
    <Heading eyebrow={<Link to="/events">{t("Events")}</Link>} title={declared?.title || event.kind} detail={event.summary}
      actions={me.can_edit && <Link to={newRule} className="button button-secondary"><Plus size={16} />{t("Create a rule from it")}</Link>} />
    {error && <ErrorBox text={error} />}
    <section className="panel">
      <dl className="al-facts">{facts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      {declared?.description && <p className="muted al-gap-top">{declared.description}</p>}
    </section>

    <h2 className="section-title">{t("Where it came from")}</h2>
    <section className="panel">
      {(url || linked.length > 0)
        ? <ul className="al-sources">
          {url && <li><a href={url}><ExternalLink size={14} /> {t("Open it in {app}", { app: appName })}</a> <span className="muted small">{t("the page the app links to this event")}</span></li>}
          {linked.map(([ref, item]) => <li key={ref}><a href={item.href ?? undefined}><ExternalLink size={14} /> {item.kind_label || refKind(ref)}: {item.title || ref}</a></li>)}
        </ul>
        : <p className="muted">{t("{app} sent no link with this event.", { app: appName })}</p>}
      {sent.length > 0 && <>
        <h3 className="al-sub">{t("What {app} sent", { app: appName })}</h3>
        <dl className="al-facts">{sent.map(([key, value]) => <div key={key}><dt>{key.replace(/_/g, " ")}</dt><dd>{shown(value)}</dd></div>)}</dl>
      </>}
    </section>

    {detail.history.length > 0 && <>
      <h2 className="section-title">{t("The same condition before")}</h2>
      <DataTable rows={detail.history} rowKey={(row) => String(row.id)} label={t("The same condition before")} initialSort={{ key: "at", descending: true }}
        onRowClick={(row) => navigate(`/events/${row.id}`)}
        columns={[
          { key: "at", label: t("When"), className: "small nowrap", sort: (row) => row.at, render: (row) => <span title={formatDate(row.at)}>{formatAgo(row.at)}</span> },
          { key: "phase", label: t("What"), className: "small", render: (row) => t(PHASE_WORDS[row.phase ?? "instant"] ?? "Happened") },
          { key: "severity", label: t("Severity"), className: "small", render: (row) => (row.severity ? <Pill status={SEVERITY_PILL[row.severity] ?? "unknown"} label={t(SEVERITY_WORDS[row.severity] ?? row.severity)} /> : "–") },
          { key: "summary", label: t("Summary"), className: "small al-wrap", render: (row) => row.summary },
        ]} />
    </>}

    <h2 className="section-title">{t("Rules")}</h2>
    <section className="panel">
      {event.rules.length > 0 && <p>{t("This event counted for:")} {event.rules.map((rule, index) => <span key={rule}>{index > 0 && ", "}<Link to={`/rules/${rule}`}>{event.rule_names?.[index] ?? rule}</Link></span>)}</p>}
      {detail.kind_rules.length > 0
        ? <p className="muted">{t("Rules that read {kind}:", { kind: event.kind })} {detail.kind_rules.map((rule, index) => <span key={rule.rule_id}>{index > 0 && ", "}<Link to={`/rules/${rule.rule_id}`}>{rule.name}</Link></span>)}</p>
        : <p className="muted">{t("No rule reads this type of event: it notifies nobody. Create a rule from it when it should become an alarm.")}</p>}
    </section>
  </>;
}
