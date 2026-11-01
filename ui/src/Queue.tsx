/**
 * An app's work queue, drawn the same way in every app: the numbers of now
 * and the items in the queue over time. The app serves `GET <app>/api/queue?window=24h` with
 * the SDK's `queue_answer` (`plantcraft_sdk.server.queue`, format `plantcraft-queue/1`) and
 * passes its own Plotly component, as with the time chart: this package draws no chart itself.
 */
import { useEffect, useState, type ComponentType, type ReactNode } from "react";
import { BRAND_COLORS, currentTheme, plotFontSize, plotTheme, type BrandTheme } from "./brandTheme.js";
import { formatAgo, formatDuration, formatNumber } from "./format.js";
import { t } from "./i18n.js";
import { timeChartLayout, timePlotConfig, windowLabel } from "./timeChart.js";

export const QUEUE_FORMAT = "plantcraft-queue/1";
export const QUEUE_WINDOWS = ["1h", "24h", "7d", "30d"] as const;
export type QueueWindow = (typeof QUEUE_WINDOWS)[number];
/** How often a queue panel asks again. */
export const QUEUE_POLL_MS = 15_000;

export type QueueNow = {
  at: string;
  queued: number;
  running: number;
  workers: number;
  busy: number;
  done: number;
  failed: number;
  cancelled: number;
  done_hour: number;
  failed_hour: number;
  cancelled_hour: number;
  skipped_hour: number;
  delay_seconds: number;
  average_seconds: number | null;
  cpu_percent: number | null;
  memory_mb: number | null;
};

export type QueuePoint = {
  at: string;
  queued: number;
  running: number;
  workers: number;
  done: number;
  failed: number;
  cancelled: number;
  delay_seconds: number;
  average_seconds: number | null;
};

export type QueueAnswer = { format: string; window: string; sample_seconds: number; now: QueueNow; history: QueuePoint[] };

/** The app's Plotly component (react-plotly.js or the app's own wrapper). */
export type QueuePlot = ComponentType<{ data: unknown[]; layout: Record<string, unknown>; config?: Record<string, unknown>; style?: Record<string, unknown>; useResizeHandler?: boolean }>;

/** The tiles of now: label, value and, when it matters, a tone. */
export function queueTiles(now: QueueNow): Array<{ id: string; label: string; value: string; detail?: string; tone?: string }> {
  return [
    { id: "queued", label: t("In the queue"), value: formatNumber(now.queued, 0), detail: now.queued ? t("oldest waiting {time}", { time: formatDuration(now.delay_seconds) }) : t("nothing waiting") },
    { id: "running", label: t("Running"), value: formatNumber(now.running, 0), detail: t("{busy} of {workers} workers busy", { busy: now.busy, workers: now.workers }) },
    { id: "done", label: t("Done in the last hour"), value: formatNumber(now.done_hour, 0), detail: now.average_seconds !== null ? t("{time} each on average", { time: formatDuration(now.average_seconds) }) : undefined },
    { id: "failed", label: t("Failed in the last hour"), value: formatNumber(now.failed_hour, 0), tone: now.failed_hour ? "problem" : undefined, detail: [now.skipped_hour ? t("{count} skipped", { count: now.skipped_hour }) : "", now.cancelled_hour ? t("{count} cancelled", { count: now.cancelled_hour }) : ""].filter(Boolean).join(" · ") || undefined },
  ];
}

/** The windows as seconds, for the chart's time axis. */
export const QUEUE_WINDOW_SECONDS: Record<QueueWindow, number> = { "1h": 3600, "24h": 86_400, "7d": 7 * 86_400, "30d": 30 * 86_400 };

/** Plotly traces and layout of the history: the queue as an area, running as a line, the
 * wait on the right axis. With `window` the time axis spans the whole window, ending at `end`
 * (now), even while the history holds a few samples only. */
export function queueChart(history: QueuePoint[], options: { height?: number; theme?: BrandTheme; delay?: boolean; window?: QueueWindow; end?: string } = {}) {
  const theme = options.theme ?? currentTheme();
  const colors = BRAND_COLORS[theme];
  const x = history.map((point) => point.at);
  const delay = options.delay ?? true;
  const data: unknown[] = [
    { x, y: history.map((point) => point.queued), name: t("In the queue"), type: "scatter", mode: "lines", fill: "tozeroy", line: { color: colors.primary, width: 1.5, shape: "hv" }, hovertemplate: `%{y}<extra>${t("In the queue")}</extra>` },
    { x, y: history.map((point) => point.running), name: t("Running"), type: "scatter", mode: "lines", line: { color: colors.good, width: 1.5, shape: "hv" }, hovertemplate: `%{y}<extra>${t("Running")}</extra>` },
  ];
  if (delay) data.push({ x, y: history.map((point) => Math.round(point.delay_seconds / 6) / 10), name: t("Wait (min)"), type: "scatter", mode: "lines", yaxis: "y2", line: { color: colors.attention, width: 1.2, dash: "dot" }, hovertemplate: `%{y} min<extra>${t("Wait")}</extra>` });
  const base = plotTheme(theme);
  const layout = {
    ...timeChartLayout(base, { height: options.height ?? 260, rightAxis: delay, ...queueRange(options.window, options.end) }),
    yaxis: { ...base.yaxis, rangemode: "tozero", title: { text: t("Items"), font: { size: plotFontSize(10.5) } } },
    ...(delay ? { yaxis2: { ...base.yaxis, overlaying: "y", side: "right", rangemode: "tozero", showgrid: false, title: { text: t("Wait (min)"), font: { size: plotFontSize(10.5) } } } } : {}),
  };
  return { data, layout };
}

function queueRange(window: QueueWindow | undefined, end: string | undefined): { start?: string; end?: string } {
  if (!window) return {};
  const stop = end ? new Date(end) : new Date();
  if (Number.isNaN(stop.getTime())) return {};
  return { start: new Date(stop.getTime() - QUEUE_WINDOW_SECONDS[window] * 1000).toISOString(), end: stop.toISOString() };
}

/** Reads `<base>api/queue?window=` every `QUEUE_POLL_MS`. */
export function useQueue(url: string, window: string, fetcher: typeof fetch = fetch): { answer: QueueAnswer | null; error: string } {
  const [answer, setAnswer] = useState<QueueAnswer | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    const read = async () => {
      try {
        const response = await fetcher(`${url}${url.includes("?") ? "&" : "?"}window=${encodeURIComponent(window)}`, { credentials: "same-origin", headers: { Accept: "application/json" } });
        if (!response.ok) throw new Error(`${response.status}`);
        const body = (await response.json()) as QueueAnswer;
        if (live) { setAnswer(body); setError(""); }
      } catch (err) {
        if (live) setError(t("The queue could not be read ({reason}).", { reason: err instanceof Error ? err.message : String(err) }));
      }
    };
    void read();
    const timer = setInterval(() => void read(), QUEUE_POLL_MS);
    return () => { live = false; clearInterval(timer); };
  }, [url, window, fetcher]);
  return { answer, error };
}

export type QueuePanelProps = {
  /** The app's queue endpoint, `api/queue` under the app's prefix. */
  url: string;
  Plot: QueuePlot;
  title?: string;
  /** Under the title (what the queue holds). */
  detail?: ReactNode;
  /** Beside the window buttons (a link to the full page, an action). */
  actions?: ReactNode;
  /** The window shown first. */
  window?: QueueWindow;
  fetcher?: typeof fetch;
};

/** The numbers of now and the history with its window (1 h, 24 h, 7 days, 30 days). */
export function QueuePanel({ url, Plot, title, detail, actions, window: first = "24h", fetcher }: QueuePanelProps) {
  const [window, setWindow] = useState<QueueWindow>(first);
  const { answer, error } = useQueue(url, window, fetcher);
  return <section className="panel pc-queue" aria-label={title ?? t("Queue")}>
    <div className="panel-header">
      <div><h2>{title ?? t("Queue")}</h2>{detail && <p>{detail}</p>}</div>
      <div className="pc-queue-actions">
        {actions}
        <div className="pc-segmented" role="group" aria-label={t("Period")}>
          {QUEUE_WINDOWS.map((item) => <button key={item} type="button" className={item === window ? "on" : ""} aria-pressed={item === window} onClick={() => setWindow(item)}>{windowLabel(item)}</button>)}
        </div>
      </div>
    </div>
    {error && <p className="pc-queue-error" role="alert">{error}</p>}
    {answer && <>
      <div className="pc-queue-tiles">
        {queueTiles(answer.now).map((tile) => <div key={tile.id} className={`kpi-card pc-queue-tile${tile.tone ? ` pc-queue-${tile.tone}` : ""}`}>
          <small>{tile.label}</small><b className="kpi-value pc-num">{tile.value}</b>{tile.detail && <small>{tile.detail}</small>}
        </div>)}
      </div>
      <QueueChart history={answer.history} Plot={Plot} window={window} end={answer.now.at} />
      <p className="pc-queue-foot">{t("Updated {when}; a sample every {seconds} s, kept 30 days.", { when: formatAgo(answer.now.at), seconds: answer.sample_seconds })}{answer.now.memory_mb !== null ? ` ${t("Workers use {cpu} CPU and {memory} MB.", { cpu: answer.now.cpu_percent !== null ? `${formatNumber(answer.now.cpu_percent, 0)} %` : "—", memory: formatNumber(answer.now.memory_mb, 0) })}` : ""}</p>
    </>}
  </section>;
}

function QueueChart({ history, Plot, height, delay, window, end }: { history: QueuePoint[]; Plot: QueuePlot; height?: number; delay?: boolean; window?: QueueWindow; end?: string }) {
  if (!history.length) return <p className="pc-queue-empty">{t("No samples in this period yet.")}</p>;
  const { data, layout } = queueChart(history, { height, delay, window, end });
  return <Plot data={data} layout={layout} config={timePlotConfig({ modeBar: false })} style={{ width: "100%" }} useResizeHandler />;
}

/** The compact form for an Overview widget: queued, running, failed and the last 24 hours. */
export function QueueSummary({ url, Plot, href, fetcher }: { url: string; Plot: QueuePlot; href?: string; fetcher?: typeof fetch }) {
  const { answer, error } = useQueue(url, "24h", fetcher);
  if (error) return <p className="pc-queue-error">{error}</p>;
  if (!answer) return <p className="pc-queue-empty">{t("Reading the queue…")}</p>;
  const now = answer.now;
  const body = <>
    <div className="pc-queue-summary">
      <span><b className="pc-num">{formatNumber(now.queued, 0)}</b><small>{t("in the queue")}</small></span>
      <span><b className="pc-num">{formatNumber(now.running, 0)}</b><small>{t("running")}</small></span>
      <span className={now.failed_hour ? "pc-queue-problem" : ""}><b className="pc-num">{formatNumber(now.failed_hour, 0)}</b><small>{t("failed, last hour")}</small></span>
    </div>
    <QueueChart history={answer.history} Plot={Plot} height={120} delay={false} window="24h" end={now.at} />
  </>;
  return href ? <a className="pc-queue-link" href={href}>{body}</a> : <div>{body}</div>;
}
