/**
 * The parts of an assistant's answer that Desk's Assistant and the side panel draw the same way
 * (owner, 2026-10-26): what is happening while the answer is written (thinking, which read is
 * running, drawing the chart, writing), and the charts it drew, with full screen, one plot or
 * one per signal, and a way to go on with the same signals and period in Trends.
 */
import { LineChart, LoaderCircle, Maximize2, Minimize2, Rows3, Square } from "lucide-react";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { t } from "./i18n.js";
import { wallClock } from "./timeZone.js";

const TimeChart = lazy(() => import("./Plot.js").then((module) => ({ default: module.TimeChart })));

export type AssistantChartSeries = { signal: string; kind?: string | null; unit?: string | null; t: string[]; v: Array<number | string | null> };
/** A chart of an answer: drawn from the plant's history by PlantCraft, never by the model.
 * `trends`: the page that opens these signals over this period in Trends (View), when installed. */
export type AssistantChartData = { title: string; start: string; end: string; series: AssistantChartSeries[]; errors?: Array<{ signal: string; detail: string }>; trends?: string | null };
export type AssistantStepView = { tool: string; title: string; state: "running" | "ok" | "error" };
/** What the progress line reads of a message being written. */
export type AssistantWorkingMessage = { state: "working" | "done" | "failed"; text: string; steps: AssistantStepView[]; created_at?: string; meta?: { queued?: boolean } };

/** What the answer is doing now, in words: null once the text is being written (it shows itself). */
export function answerPhase(message: AssistantWorkingMessage): string | null {
  if (message.state !== "working") return null;
  if (message.meta?.queued) return t("Waiting for a free slot…");
  const running = [...message.steps].reverse().find((step) => step.state === "running");
  if (running) {
    if (running.tool === "show_chart") return t("Drawing the chart…");
    if (running.tool === "propose" || running.tool === "propose_create") return t("Preparing the card…");
    return t("Reading: {what}…", { what: t(running.title) });
  }
  if (message.text) return null;
  return message.steps.length ? t("Thinking about what it read…") : t("Thinking…");
}

/** Whole seconds since `start` (ISO), counted while `on`. */
function useSeconds(start: string | undefined, on: boolean): number | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!on) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [on]);
  const begun = start ? Date.parse(start.endsWith("Z") || start.includes("+") ? start : `${start}Z`) : NaN;
  return Number.isNaN(begun) ? null : Math.max(0, Math.round((now - begun) / 1000));
}

/** The line under an answer being written: what it is doing, and for how long. */
export function AnswerProgress({ message, className = "pc-answer-progress" }: { message: AssistantWorkingMessage; className?: string }) {
  const working = message.state === "working";
  const seconds = useSeconds(message.created_at, working);
  if (!working) return null;
  const phase = answerPhase(message) ?? t("Writing…");
  return <p className={className} role="status" aria-live="polite">
    <span className="pc-answer-dots" aria-hidden="true"><i /><i /><i /></span>
    <span>{phase}</span>
    {seconds !== null && seconds >= 2 && <small>{t("{count} s", { count: seconds })}</small>}
  </p>;
}

/** One plot or one per signal: separate when the signals' ranges are far apart (a mode at 0
 * beside a flow at 300 is a flat line on a shared axis). */
export function splitByDefault(series: AssistantChartSeries[]): boolean {
  const spans = series
    .map((item) => item.v.filter((value): value is number => typeof value === "number" && Number.isFinite(value)))
    .filter((values) => values.length > 0)
    .map((values) => Math.max(Math.abs(Math.max(...values)), Math.abs(Math.min(...values)), Math.max(...values) - Math.min(...values)));
  if (spans.length < 2) return false;
  const units = new Set(series.map((item) => item.unit || "").filter(Boolean));
  const largest = Math.max(...spans);
  const smallest = Math.max(Math.min(...spans), 1e-9);
  return units.size > 1 || largest / smallest > 10;
}

/** The trends page for these signals, on the platform's host (an app's panel too). */
export function trendsHref(chart: AssistantChartData, base?: string | null): string | null {
  if (!chart.trends) return null;
  if (!base) return chart.trends;
  try { return new URL(chart.trends, base).toString(); } catch { return chart.trends; }
}

/** A chart of an answer, the same in Desk and in the side panel. */
export function AssistantChart({ chart, base, height = 260, className = "pc-answer-chart" }: { chart: AssistantChartData; base?: string | null; height?: number; className?: string }) {
  const box = useRef<HTMLElement>(null);
  const drawn = chart.series.filter((item) => item.v.length > 0);
  const empty = chart.series.filter((item) => !item.v.length);
  const [split, setSplit] = useState(() => splitByDefault(drawn));
  const [full, setFull] = useState(false);
  useEffect(() => {
    const changed = () => setFull(document.fullscreenElement === box.current && box.current !== null);
    document.addEventListener("fullscreenchange", changed);
    return () => document.removeEventListener("fullscreenchange", changed);
  }, []);
  async function toggleFull() {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await box.current?.requestFullscreen();
    } catch { setFull((value) => !value); }
  }
  const lines = drawn.map((item) => ({ name: item.signal, unit: item.unit || undefined, t: item.t, v: item.v, text: item.kind === "text" || item.v.every((value) => typeof value !== "number") }));
  const groups = split && lines.length > 1 ? lines.map((line) => [line]) : [lines];
  const tall = full ? Math.max(240, (typeof window === "undefined" ? 800 : window.innerHeight) - 120) : height;
  const each = groups.length > 1 ? Math.max(full ? 160 : 130, Math.round(tall / groups.length)) : tall;
  // In the suite's display time zone, like Trends and every chart (not the browser's).
  const when = (value: string) => { const ms = Date.parse(value); return Number.isNaN(ms) ? value : wallClock(ms).slice(0, 16); };
  const trends = trendsHref(chart, base);
  return <figure ref={box} className={`${className}${full ? " pc-answer-chart-full" : ""}`}>
    <figcaption>
      <span><strong>{chart.title || chart.series.map((item) => item.signal).join(", ")}</strong><small>{when(chart.start)} – {when(chart.end)}</small></span>
      <span className="pc-answer-chart-tools">
        {lines.length > 1 && <button type="button" onClick={() => setSplit((value) => !value)} title={split ? t("All on one plot") : t("One plot per signal")} aria-label={split ? t("All on one plot") : t("One plot per signal")}>{split ? <Square size={14} /> : <Rows3 size={14} />}</button>}
        {trends && <a href={trends} title={t("Open in Trends to go on with the analysis")}><LineChart size={14} aria-hidden="true" />{t("Open in Trends")}</a>}
        <button type="button" onClick={() => void toggleFull()} title={full ? t("Leave full screen") : t("Full screen")} aria-label={full ? t("Leave full screen") : t("Full screen")}>{full ? <Minimize2 size={14} /> : <Maximize2 size={14} />}</button>
      </span>
    </figcaption>
    {lines.length > 0 && <Suspense fallback={<div className="pc-answer-chart-wait"><LoaderCircle className="spin" size={16} /></div>}>
      {groups.map((group) => <TimeChart key={group.map((line) => line.name).join("|")} lines={group} height={each} start={chart.start} end={chart.end} filename={chart.title || "assistant-chart"} />)}
    </Suspense>}
    {empty.length > 0 && <p className="pc-answer-chart-note">{t("No data in this period: {signals}", { signals: empty.map((item) => item.signal).join(", ") })}</p>}
    {(chart.errors ?? []).length > 0 && <p className="pc-answer-chart-errors">{(chart.errors ?? []).map((item) => `${item.signal}: ${item.detail}`).join(" · ")}</p>}
    <small className="pc-answer-chart-source">{t("Drawn from the plant's history, not by the model.")}</small>
  </figure>;
}
