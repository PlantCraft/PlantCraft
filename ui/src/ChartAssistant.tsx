/**
 * The assistant on each chart (a trial, 2026-11-02, off by default: `PLANTCRAFT_ASSISTANT_CHARTS`).
 * A small popover over the chart asks and answers in place: "Explain this chart", "What stands
 * out?", "What could explain this?" or the person's own words. The model gets what the chart
 * draws (each line's name, period, range, mean, last value and a few points), reads the plant as
 * the person through the same tools as the side panel (docs/assistant.md), and changes nothing.
 * The chat is not kept: it is deleted a day later unless the person continues it in Desk.
 *
 * It is reached from the assistant's mark in each chart's row of buttons (the row Plotly shows on
 * hover; owner's pick, 2026-11-02, over a "focus" item in the menu beside the page's title).
 * `Plot` (Plot.tsx) does it for every chart of every app; a chart opts out with `assistant={false}`.
 */
import { AlertTriangle, ArrowUp, ExternalLink, LoaderCircle, X } from "lucide-react";
import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore, type FormEvent, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { AnswerProgress } from "./AssistantAnswer.js";
import { AssistantMark, assistantStatus, forgetAssistantStatus, useAssistantPlaceValue, usePageSource } from "./AssistantDrawer.js";
import { useDismiss } from "./dismiss.js";
import { platformPath } from "./Journey.js";
import { renderMarkdown } from "./Markdown.js";
import { t } from "./i18n.js";
import { displayTimeZone } from "./timeZone.js";

/** Whether the assistant is offered on charts (`charts` in `GET /api/assistant`, from
 * `PLANTCRAFT_ASSISTANT_CHARTS`): "icon" puts its mark in each chart's buttons. */
export type ChartAssistantMode = "off" | "icon";
/** A person trying it in their own browser: `localStorage["pc-assistant-charts"] = "icon"` (or "off"). */
export const CHART_MODE_KEY = "pc-assistant-charts";

/** The mode PlantCraft sets, or the one this browser tries; always off where no model answers. */
export function chartModeOf(status: { available?: boolean; charts?: string } | null | undefined): ChartAssistantMode {
  if (!status?.available) return "off";
  let tried: string | null = null;
  try { tried = window.localStorage.getItem(CHART_MODE_KEY); } catch { tried = null; }
  return (tried ?? status.charts) === "icon" ? "icon" : "off";
}

// The chart whose popover is open: one at a time for the page.
let opened: string | null = null;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((listener) => listener());
const subscribe = (listener: () => void) => { listeners.add(listener); return () => listeners.delete(listener); };
/** Open the assistant's popover over this chart (closing any other). */
export function openChartAssistant(id: string) { opened = id; emit(); }
export function closeChartAssistant() { if (opened === null) return; opened = null; emit(); }
function forgetChart(id: string) { if (opened === id) closeChartAssistant(); }
export function useOpenedChart(): string | null { return useSyncExternalStore(subscribe, () => opened, () => null); }

/** What a chart tells the assistant about itself, beyond what it draws. */
export type ChartAssistantOptions = {
  /** The chart's name in the popover ("FIC-101 PV and SP"); left out, the figure's title or its lines. */
  title?: string;
  /** The object the chart is about (`asset:FIC-101`, `run:linkcraft/42`). */
  subject?: string;
  /** More for the model: what the chart is for, its limits. */
  context?: string;
};

/** One thing to ask about a chart. */
export type ChartQuestion = { label: string; instructions: string };

/** The questions every chart offers. */
export function chartQuestions(): ChartQuestion[] {
  return [
    { label: t("Explain this chart"), instructions: "Explain what this chart shows: what each line is, its level and trend over the period, and what stands out. Read the plant (the signals, their asset, events and alarms) when the values alone cannot say why. At most six short lines." },
    { label: t("What stands out?"), instructions: "Point out what is unusual on this chart: jumps, spikes, flat lines, oscillation, gaps, a line leaving its usual range. Say when each happened, in the page's time zone. If nothing stands out, say so in one line." },
    { label: t("What could explain this?"), instructions: "Find what could explain the main change on this chart: events, alarms, operator actions and related signals in the same period. Name the read behind each cause, and say so when the reads cannot tell." },
  ];
}

type Trace = { name?: unknown; type?: unknown; x?: unknown; y?: unknown; z?: unknown };

const SAMPLES = 24;
const MAX_TRACES = 8;
const MAX_CONTEXT = 3500;

const number = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);
const short = (value: number) => Number(value.toPrecision(4)).toString();
// Times as ISO without milliseconds (".000Z" is noise for the model).
const text = (value: unknown) => (value instanceof Date ? value.toISOString() : String(value)).replace(/\.000(Z|[+-]\d\d:\d\d)$/, "$1");

/** The chart's name: the one given, the figure's title, or its lines. */
export function chartTitle(data: readonly unknown[], layout: unknown, given?: string): string {
  if (given?.trim()) return given.trim();
  const title = (layout as { title?: unknown } | undefined)?.title;
  const named = typeof title === "string" ? title : typeof (title as { text?: unknown } | undefined)?.text === "string" ? (title as { text: string }).text : "";
  if (named.trim()) return named.replace(/<[^>]+>/g, "").trim();
  const names = (data as Trace[]).map((trace) => (typeof trace?.name === "string" ? trace.name : "")).filter(Boolean);
  return names.length ? names.slice(0, 3).join(", ") + (names.length > 3 ? "…" : "") : t("This chart");
}

/** What the chart draws, as the model reads it: per line its period, range, mean, last value and
 * a few points (evenly spread, its lowest and highest kept). Never the whole series. */
export function chartContext(data: readonly unknown[], layout: unknown, title: string): string {
  let zone = "UTC";
  try { zone = displayTimeZone(); } catch { zone = "UTC"; }
  const lines: string[] = [`Chart: ${title}`, `Times below are UTC; the person reads them in ${zone}.`];
  const axis = (key: "xaxis" | "yaxis") => {
    const found = (layout as Record<string, { title?: unknown } | undefined> | undefined)?.[key]?.title;
    return typeof found === "string" ? found : typeof (found as { text?: unknown } | undefined)?.text === "string" ? String((found as { text: string }).text) : "";
  };
  const [xName, yName] = [axis("xaxis"), axis("yaxis")];
  if (xName || yName) lines.push(`Axes: x ${xName || "-"}, y ${yName || "-"}`);
  const traces = (data as Trace[]).filter((trace) => trace && typeof trace === "object");
  traces.slice(0, MAX_TRACES).forEach((trace, index) => {
    const name = typeof trace.name === "string" && trace.name ? trace.name : `Series ${index + 1}`;
    if (trace.z !== undefined) { lines.push(`- ${name}: a ${String(trace.type ?? "heatmap")} (values not listed)`); return; }
    const ys = Array.isArray(trace.y) ? trace.y : [];
    const xs = Array.isArray(trace.x) ? trace.x : ys.map((_, at) => at);
    const values = ys.map(number);
    const present = values.flatMap((value, at) => (value === null ? [] : [{ at, value }]));
    if (!present.length) {
      const states = [...new Set(ys.filter((value) => value !== null && value !== undefined).map(text))].slice(0, 8);
      lines.push(`- ${name}: ${ys.length} points${states.length ? `, states ${states.join(", ")}` : ", no values"}`);
      return;
    }
    let low = present[0]!, high = present[0]!, sum = 0;
    for (const item of present) { if (item.value < low.value) low = item; if (item.value > high.value) high = item; sum += item.value; }
    const first = present[0]!, last = present[present.length - 1]!;
    const gaps = ys.length - present.length;
    if (low.value === high.value) {
      lines.push(`- ${name}: ${present.length} points from ${text(xs[first.at])} to ${text(xs[last.at])}, constant at ${short(low.value)}${gaps ? `, ${gaps} empty` : ""}`);
      return;
    }
    lines.push(`- ${name}: ${present.length} points from ${text(xs[first.at])} to ${text(xs[last.at])}; min ${short(low.value)} at ${text(xs[low.at])}, max ${short(high.value)} at ${text(xs[high.at])}, mean ${short(sum / present.length)}, first ${short(first.value)}, last ${short(last.value)}${gaps ? `, ${gaps} empty` : ""}`);
    const picks = new Set<number>([low.at, high.at]);
    const step = Math.max(1, Math.ceil(present.length / SAMPLES));
    for (let at = 0; at < present.length; at += step) picks.add(present[at]!.at);
    picks.add(last.at);
    const points = [...picks].sort((a, b) => a - b).map((at) => `${text(xs[at])} ${short(values[at]!)}`);
    lines.push(`  points: ${points.join("; ")}`);
  });
  if (traces.length > MAX_TRACES) lines.push(`(${traces.length - MAX_TRACES} more series not listed)`);
  const joined = lines.join("\n");
  return joined.length > MAX_CONTEXT ? `${joined.slice(0, MAX_CONTEXT)}…` : joined;
}

type Status = { available?: boolean; charts?: string; visit?: { questions: number; max_text: number; left: number } };

/** How the assistant is offered on this chart: off where no shell draws the assistant, where no
 * model answers, or where the chart opted out. */
export function useChartAssistantMode(enabled: boolean): { mode: ChartAssistantMode; platformUrl?: string | null } {
  const source = usePageSource();
  const described = useAssistantPlaceValue();
  const platformUrl = described?.platformUrl ?? source?.platformUrl;
  const [status, setStatus] = useState<Status | null>(null);
  useEffect(() => {
    if (!enabled || !source) return;
    let alive = true;
    void assistantStatus(platformUrl).then((value) => alive && setStatus(value as Status | null));
    return () => { alive = false; };
  }, [enabled, Boolean(source), platformUrl]); // eslint-disable-line react-hooks/exhaustive-deps
  return { mode: enabled && source ? chartModeOf(status) : "off", platformUrl };
}

// The assistant's mark for Plotly's row of buttons (24 × 24, drawn without Plotly's flip).
const MARK_PATH = "M7.5 1.5h9a6 6 0 0 1 6 6v9a6 6 0 0 1-6 6h-9a6 6 0 0 1-6-6v-9a6 6 0 0 1 6-6Zm0 1.8a4.2 4.2 0 0 0-4.2 4.2v9a4.2 4.2 0 0 0 4.2 4.2h9a4.2 4.2 0 0 0 4.2-4.2v-9a4.2 4.2 0 0 0-4.2-4.2ZM11 5.6c.3 2.9 1.9 4.6 4.9 5-3 .4-4.6 2.1-4.9 5-.3-2.9-1.9-4.6-4.9-5 3-.4 4.6-2.1 4.9-5Zm5.6 8.6c.15 1.35.9 2.1 2.2 2.25-1.3.15-2.05.9-2.2 2.25-.15-1.35-.9-2.1-2.2-2.25 1.3-.15 2.05-.9 2.2-2.25Z";

/** The chart's Plotly config with the assistant's button: added to its row, or the only button
 * of a chart that hides the row (a small card). */
export function chartConfig(config: Record<string, unknown> | undefined, open: () => void): Record<string, unknown> {
  const button = { name: "assistant", title: t("Ask the assistant about this chart"), icon: { width: 24, height: 24, path: MARK_PATH }, click: open };
  const base = { ...(config ?? {}) };
  if (base.displayModeBar === false) {
    delete base.displayModeBar;
    return { ...base, modeBarButtons: [[button]] };
  }
  const added = Array.isArray(base.modeBarButtonsToAdd) ? base.modeBarButtonsToAdd : [];
  return { ...base, modeBarButtonsToAdd: [...added, button] };
}

/** What `Plot` needs to offer the assistant on its chart: the config with its button, where to
 * follow the chart's box, and the popover when it is open. */
export function useChartAssistant(options: ChartAssistantOptions | false | undefined, data: readonly unknown[], layout: unknown, config: Record<string, unknown> | undefined) {
  const id = useId();
  const { mode, platformUrl } = useChartAssistantMode(options !== false);
  const own = options || undefined;
  const title = useMemo(() => chartTitle(data, layout, own?.title), [data, layout, own?.title]);
  const latest = useRef({ data, layout, title, own });
  latest.current = { data, layout, title, own };
  const [node, setNode] = useState<HTMLElement | null>(null);
  const open = useCallback(() => openChartAssistant(id), [id]);
  const finalConfig = useMemo(() => (mode === "icon" ? chartConfig(config, open) : config), [mode, config, open]);
  useEffect(() => () => forgetChart(id), [id]);
  const opened = useOpenedChart() === id;
  const describe = useCallback(() => {
    const { data: drawn, layout: laid, title: named, own: given } = latest.current;
    return [chartContext(drawn, laid, named), given?.context?.trim()].filter(Boolean).join("\n\n");
  }, []);
  const popover = opened && node && mode !== "off" && typeof document !== "undefined"
    ? createPortal(<ChartPopover anchor={node} title={title} subject={own?.subject} describe={describe} platformUrl={platformUrl} onClose={closeChartAssistant} />, document.body)
    : null;
  return { config: finalConfig, follow: setNode, popover, mode };
}

type Message = { message_id: number; role: "user" | "assistant"; text: string; state: "working" | "done" | "failed"; steps: Array<{ tool: string; title: string; state: "running" | "ok" | "error" }>; created_at?: string; meta?: { queued?: boolean } };

async function call<T>(base: string | null | undefined, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(platformPath(base, path), { credentials: "same-origin", ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload && typeof payload === "object" && "detail" in payload ? String((payload as { detail: unknown }).detail) : "";
    throw new Error(detail || t("Couldn't connect to the server."));
  }
  return payload as T;
}

const POLL_MS = 700;
const WIDTH = 380;

/** Where the popover sits: over the chart's top right corner, inside the screen; on a phone, at
 * the bottom of the screen. */
export function popoverPlace(rect: { top: number; right: number }, screen: number, scroll: { x: number; y: number }): Record<string, string> {
  if (screen < 600) return { position: "fixed", left: "16px", right: "16px", bottom: "16px" };
  const width = Math.min(WIDTH, screen - 32);
  const left = Math.max(16, Math.min(rect.right - width - 8, screen - 16 - width));
  return { position: "absolute", width: `${width}px`, left: `${left + scroll.x}px`, top: `${Math.max(8, rect.top + 8) + scroll.y}px` };
}

/** The popover: what to ask about the chart, the answer as it is written, a follow-up, and
 * "Continue in Desk". Nothing is kept unless the person continues it there. */
export function ChartPopover({ anchor, title, subject, describe, platformUrl, onClose }: { anchor: HTMLElement; title: string; subject?: string; describe: () => string; platformUrl?: string | null; onClose: () => void }) {
  const box = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [chatId, setChatId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [style, setStyle] = useState<Record<string, string>>({});
  const place = useAssistantPlaceValue();
  const working = messages.some((item) => item.state === "working");
  useDismiss(true, onClose, box);
  useEffect(() => { let alive = true; void assistantStatus(platformUrl).then((value) => alive && setStatus(value as Status | null)); return () => { alive = false; }; }, [platformUrl]);
  useLayoutEffect(() => {
    const rect = anchor.getBoundingClientRect();
    setStyle(popoverPlace(rect, document.documentElement.clientWidth || window.innerWidth, { x: window.scrollX, y: window.scrollY }));
  }, [anchor]);
  useEffect(() => {
    if (chatId === null || !working) return;
    const timer = window.setInterval(async () => {
      try {
        const view = await call<{ messages: Message[] }>(platformUrl, `api/assistant/chats/${chatId}`);
        setMessages(view.messages);
      } catch { /* the next poll tries again */ }
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [platformUrl, chatId, working]);

  async function ask(question: string, instructions = "") {
    const clean = question.trim();
    if (!clean || busy || working) return;
    setBusy(true); setError("");
    try {
      if (chatId === null) {
        const context = [`The person asked from a chart on the page, in a small popover over it: answer short, the chart is beside the answer.`,
          instructions && `What to do: ${instructions}`, describe(), place?.context?.trim() && `The page:\n${place.context.trim()}`].filter(Boolean).join("\n\n").slice(0, 4000);
        const started = await call<{ chat: { chat_id: number }; messages: Message[] }>(platformUrl, "api/assistant/chats", { method: "POST", body: JSON.stringify({ text: clean, ref: subject ?? place?.subject ?? "", place: [place?.place, title].filter(Boolean).join(" › "), context, keep: false }) });
        setChatId(started.chat.chat_id);
        setMessages(started.messages);
      } else {
        const asked = await call<{ messages: Message[] }>(platformUrl, `api/assistant/chats/${chatId}/messages`, { method: "POST", body: JSON.stringify({ text: clean }) });
        setMessages((value) => [...value.filter((item) => !asked.messages.some((fresh) => fresh.message_id === item.message_id)), ...asked.messages]);
      }
      setDraft("");
      if (status?.visit) { forgetAssistantStatus(); setStatus((value) => (value?.visit ? { ...value, visit: { ...value.visit, left: Math.max(0, value.visit.left - 1) } } : value)); }
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(false); }
  }
  /** The chat goes on in Desk, kept there from now on. */
  async function continueInDesk() {
    if (chatId === null) return;
    await call(platformUrl, `api/assistant/chats/${chatId}/keep`, { method: "POST" }).catch(() => undefined);
    window.location.assign(platformPath(platformUrl, `assistant/${chatId}`));
  }
  function submit(event: FormEvent) { event.preventDefault(); void ask(draft); }
  function keys(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void ask(draft); }
  }
  const left = status?.visit?.left ?? null;
  return <div className="pc-chart-popover" ref={box} style={style} role="dialog" aria-label={t("Assistant: {title}", { title })}>
    <header>
      <AssistantMark size={18} />
      <span><strong>{t("Assistant")}</strong><small>{title}</small></span>
      <button type="button" className="pc-chart-popover-close" onClick={onClose} aria-label={t("Close")}><X size={15} /></button>
    </header>
    <div className="pc-chart-popover-body">
      {status === null && <p className="pc-drawer-wait"><LoaderCircle className="spin" size={13} /> {t("Loading…")}</p>}
      {status && !messages.length && <ul className="pc-chart-popover-questions">{chartQuestions().map((item) => <li key={item.label}>
        <button type="button" onClick={() => void ask(item.label, item.instructions)} disabled={busy || left === 0}>{item.label}</button>
      </li>)}</ul>}
      {messages.length > 0 && <ol className="pc-chart-popover-messages">{messages.map((message) => <li key={message.message_id} className={message.role === "user" ? "mine" : "theirs"}>
        {message.role === "user" ? <p className="pc-drawer-question">{message.text}</p>
          : message.state === "failed" ? <p className="pc-drawer-failed"><AlertTriangle size={14} /> {message.text || t("The answer was interrupted. Ask again.")}</p>
            : <>{message.text && <div className={`pc-drawer-markdown${message.state === "working" ? " pc-answer-writing" : ""}`}>{renderMarkdown(message.text, { plainExternalLinks: true })}</div>}<AnswerProgress message={message} /></>}
      </li>)}</ol>}
      {error && <p className="pc-drawer-failed"><AlertTriangle size={14} /> {error}</p>}
    </div>
    {status && <form className="pc-chart-popover-composer" onSubmit={submit}>
      <textarea value={draft} rows={1} maxLength={status.visit?.max_text ?? 2000} onChange={(event) => setDraft(event.target.value)} onKeyDown={keys}
        placeholder={messages.length ? t("Ask a follow-up") : t("Or ask about this chart")} aria-label={t("Your question")} disabled={left === 0} />
      <button type="submit" disabled={busy || working || !draft.trim() || left === 0} aria-label={t("Send")}>{busy ? <LoaderCircle className="spin" size={15} /> : <ArrowUp size={15} />}</button>
    </form>}
    <footer>
      {left !== null && status?.visit ? <small>{t("{left} of {count} questions left in this demo visit.", { left, count: status.visit.questions })}</small>
        : <small>{t("Not kept: deleted in a day unless you continue it in Desk.")}</small>}
      {chatId !== null && !working && <button type="button" className="pc-chart-popover-desk" onClick={() => void continueInDesk()}><ExternalLink size={13} aria-hidden="true" />{t("Continue in Desk")}</button>}
    </footer>
  </div>;
}
