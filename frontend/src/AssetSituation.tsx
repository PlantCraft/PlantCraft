import { useEffect, useState } from "react";
import { ChevronRight, ListChecks, Play, RefreshCw } from "lucide-react";
import { AppMark, appIdFor, appLabel, formatAgo, Pill } from "@plantcraft/ui";
import { requestJson } from "./api";
import { t } from "./i18n";
import { navigate } from "./nav";

export type SituationResult = {
  subject: string;
  about: { title: string; detail?: string | null; kind: "asset" | "signal" | "inside" | "other"; href?: string };
  kind: string;
  status: string;
  score: number | null;
  summary: string;
  at: string;
  stale: boolean;
  url: string | null;
};

export type SituationApp = { app: string; status: string; counts: Record<string, number>; results: SituationResult[] };

export type Situation = {
  asset_id: string;
  status: string | null;
  counts: Record<string, number>;
  inside: { included: number; total: number };
  apps: SituationApp[];
  events: Array<{ event_id: number; at: string; kind: string; source?: string; summary: string; actor?: string | null }>;
  runs: Array<{ app: string; id: string; name: string; status: string; started_at: string | null; finished_at: string | null; summary: string; url: string | null }>;
  actions: Array<{ action_id: number; title: string; status: string; priority: string; owner: string | null; due_at: string | null }>;
};

export const situationApi = {
  get: (id: string) => requestJson<Situation>(`/api/assets/${encodeURIComponent(id)}/situation`),
};

const STATUS_LABELS: Record<string, string> = { alarm: t("Critical"), warning: t("Warning"), unknown: t("Unknown"), ok: t("OK") };

/** The words of the page's verdict: what needs someone first. */
export function situationHeadline(situation: Pick<Situation, "status" | "counts" | "apps">): string {
  if (!situation.apps.length) return t("No app has published anything about this asset yet.");
  const { alarm = 0, warning = 0, unknown = 0 } = situation.counts;
  if (alarm) return t("{count} in alarm, {warnings} with a warning.", { count: alarm, warnings: warning });
  if (warning) return t("{count} with a warning, nothing in alarm.", { count: warning });
  if (unknown) return t("Nothing in alarm; {count} could not be judged.", { count: unknown });
  return t("Everything the apps check here is OK.");
}

/** A result's link: an app's page (absolute in the suite) or PlantCraft's own. */
function Follow({ href, children }: { href: string; children: React.ReactNode }) {
  const own = href.startsWith("/assets/") || href.startsWith("/actions/");
  return <a href={href} onClick={(event) => { if (!own || event.metaKey || event.ctrlKey || event.shiftKey) return; event.preventDefault(); navigate(href); }}>{children}</a>;
}

function kindLabel(kind: string): string {
  return kind.replace(/_/g, " ");
}

/** An asset's Situation tab (owner, 2026-10-23): alarms, Link's diagnoses, models and actions
 * of one asset, its signals and what is inside it, on one page, worst first. */
export function AssetSituation({ assetId, onActions }: { assetId: string; onActions: () => void }) {
  const [data, setData] = useState<Situation | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const load = () => situationApi.get(assetId).then((value) => { setData(value); setError(""); }).catch((err) => setError(err.message));
  useEffect(() => { setData(null); void load(); }, [assetId]);
  if (!data) return error ? <p className="error-text">{error}</p> : <p className="muted">{t("Loading the situation…")}</p>;
  return <section className="as-situation">
    <article className={`panel as-situation-head as-tone-${data.status ?? "none"}`}>
      <div>
        {data.status && <Pill status={data.status} label={STATUS_LABELS[data.status] ?? data.status} />}
        <h2>{situationHeadline(data)}</h2>
        <p className="muted">{data.inside.total
          ? t("What the suite's apps say about this asset, its signals and the {count} assets inside it.", { count: data.inside.total })
          : t("What the suite's apps say about this asset and its signals.")}
          {data.inside.total > data.inside.included && ` ${t("The first {count} inside are included.", { count: data.inside.included })}`}</p>
      </div>
      <button type="button" className="button button-secondary button-small button-icon" title={t("Refresh")} aria-label={t("Refresh")} onClick={() => void load()}><RefreshCw /></button>
    </article>
    <div className="as-situation-grid">
      <div className="as-situation-apps">
        {data.apps.map((group) => {
          const family = appIdFor(group.app);
          const shown = open[group.app] ? group.results : group.results.slice(0, 6);
          return <article key={group.app} className="panel as-situation-app">
            <header className="panel-header"><div className="as-situation-app-title">
              {family && <AppMark app={family} size={22} />}
              <h2>{appLabel(group.app, group.app)}</h2>
              <Pill status={group.status} label={STATUS_LABELS[group.status] ?? group.status} />
            </div><p>{Object.entries(group.counts).sort(([a], [b]) => Object.keys(STATUS_LABELS).indexOf(a) - Object.keys(STATUS_LABELS).indexOf(b)).map(([status, count]) => `${count} ${(STATUS_LABELS[status] ?? status).toLowerCase()}`).join(" · ")}</p></header>
            <ul className="as-situation-results">
              {shown.map((row) => <li key={`${row.subject}|${row.kind}`}>
                <i className="as-situation-dot" style={{ background: `var(--pc-${row.status === "alarm" ? "problem" : row.status === "warning" ? "attention" : row.status === "ok" ? "good" : "unusable"}-fill)` }} aria-hidden="true" />
                <div>
                  <strong>{row.about.kind === "signal" ? `${row.about.title} · ${row.about.detail ?? ""}` : row.about.title}</strong>
                  <span>{row.summary || kindLabel(row.kind)}</span>
                  <small>{kindLabel(row.kind)}{row.score !== null ? ` · ${t("score {score}", { score: Math.round(row.score) })}` : ""} · {row.stale ? t("out of date") : formatAgo(row.at)}</small>
                </div>
                {row.url ? <Follow href={row.url}><ChevronRight size={16} aria-label={t("Open in {app}", { app: appLabel(group.app, group.app) })} /></Follow> : row.about.kind === "inside" && row.about.href ? <Follow href={row.about.href}><ChevronRight size={16} aria-label={t("Open the asset")} /></Follow> : null}
              </li>)}
            </ul>
            {group.results.length > 6 && <button type="button" className="button button-small button-ghost" onClick={() => setOpen({ ...open, [group.app]: !open[group.app] })}>{open[group.app] ? t("Show fewer") : t("Show all {count}", { count: group.results.length })}</button>}
          </article>;
        })}
        {!data.apps.length && <article className="panel"><p className="muted">{t("When Analytics, Alarms, Models or another app checks this asset, its findings show here.")}</p></article>}
      </div>
      <div className="as-situation-side">
        <article className="panel"><header className="panel-header"><div><h2>{t("Open actions")}</h2><p>{t("Follow-up about this asset")}</p></div><button type="button" className="button button-small button-ghost" onClick={onActions}><ListChecks size={14} /> {t("All")}</button></header>
          <ul className="as-situation-list">{data.actions.map((item) => <li key={item.action_id}><Follow href={`/actions/${item.action_id}`}><strong>AC-{item.action_id} · {item.title}</strong></Follow><small>{[item.owner, item.due_at ? t("due {date}", { date: item.due_at.slice(0, 10) }) : null].filter(Boolean).join(" · ") || t("No owner yet")}</small></li>)}</ul>
          {!data.actions.length && <p className="muted">{t("No open action.")}</p>}
        </article>
        <article className="panel"><header className="panel-header"><div><h2>{t("Latest events")}</h2><p>{t("Alarms raised and cleared, findings, changes")}</p></div></header>
          <ol className="as-timeline">{data.events.slice(0, 10).map((event) => <li key={event.event_id}><time>{formatAgo(event.at)}</time><span>{event.summary || event.kind}</span>{event.actor && <small>{event.actor}</small>}</li>)}</ol>
          {!data.events.length && <p className="muted">{t("Nothing recorded yet.")}</p>}
        </article>
        {data.runs.length > 0 && <article className="panel"><header className="panel-header"><div><h2>{t("Recent runs")}</h2><p>{t("Runs that covered this asset")}</p></div></header>
          <ul className="as-situation-list">{data.runs.map((run) => <li key={`${run.app}/${run.id}`}><span className="as-situation-run"><Play size={13} />{run.url ? <Follow href={run.url}><strong>{run.name || run.id}</strong></Follow> : <strong>{run.name || run.id}</strong>}<Pill status={run.status} label={run.status} /></span><small>{appLabel(run.app, run.app)} · {formatAgo(run.finished_at ?? run.started_at ?? "")}</small></li>)}</ul>
        </article>}
      </div>
    </div>
  </section>;
}
