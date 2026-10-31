/** Reports in the interface: their sections, schedule and runs in people's words (the server
 * keeps the rules: `reports/model.py`). */
import { t } from "./i18n";
import { defaultCard, windowLabel } from "./model";
import type { Card, Kind, ReportDraft, ReportRun, Schedule, Section, SectionKind, Weekday } from "./types";

export const MAX_SECTIONS = 60;
export const MAX_TEXT = 20000;
/** The periods a report covers, ending when it is made; the cadence suggests one. */
export const PERIODS = ["1h", "8h", "12h", "24h", "7d", "14d", "30d", "90d", "365d"];
export const PERIOD_FOR: Record<Schedule["every"], string> = { off: "24h", day: "24h", week: "7d", fortnight: "14d", month: "30d", quarter: "90d" };
export const WEEKDAYS: Weekday[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
export const WEEKDAY_NAMES: Record<Weekday, string> = { mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday", fri: "Friday", sat: "Saturday", sun: "Sunday" };
export const SECTION_LABELS: Record<SectionKind, string> = { text: "Text", card: "Panel", events: "Events", break: "Page break", assistant: "Assistant" };
export const EXPORTS: Array<{ id: "pdf" | "docx" | "html" | "md"; label: string; hint: string }> = [
  { id: "pdf", label: "PDF", hint: "To print and to keep: the same file the schedule sends, kept in Sent." },
  { id: "docx", label: "Word (.docx)", hint: "To change and pass on: headings as Word's own, tables you can edit, charts as pictures." },
  { id: "html", label: "Web page (.html)", hint: "One file that opens anywhere, offline: the sections at the side and charts that show their values on hover." },
  { id: "md", label: "Markdown (.md)", hint: "Plain text for a wiki, a notebook or a ticket: the text as written, each panel as its values." },
];
// A report's card has no window of its own (it reads the period) and no text kind.
export const REPORT_KINDS: Kind[] = ["stat", "gauge", "trend", "bar", "table", "scatter"];

export const EMPTY_SCHEDULE: Schedule = { every: "off", at: "06:00", weekday: "mon", day: 1 };
export const EMPTY_REPORT: ReportDraft = { name: "", description: "", folder_id: "", period: "24h", schedule: EMPTY_SCHEDULE, recipients: [], email: false, sections: [] };

/** "Every day at 06:00", "Every Monday at 07:00", "Not scheduled" (as the server writes it). */
export function cadenceLabel(schedule: Schedule): string {
  if (schedule.every === "day") return t("Every day at {at}", { at: schedule.at });
  if (schedule.every === "week") return t("Every {weekday} at {at}", { weekday: t(WEEKDAY_NAMES[schedule.weekday]), at: schedule.at });
  if (schedule.every === "fortnight") return t("Every other {weekday} at {at}", { weekday: t(WEEKDAY_NAMES[schedule.weekday]), at: schedule.at });
  if (schedule.every === "month") return t("Every month on day {day} at {at}", { day: schedule.day, at: schedule.at });
  if (schedule.every === "quarter") return t("Every quarter on day {day} at {at}", { day: schedule.day, at: schedule.at });
  return t("Not scheduled");
}

/** "The last 24 hours", "The last 7 days". */
export function periodLabel(period: string): string {
  return t("The last {window}", { window: windowLabel(period) });
}

/** A section id not used yet in the report: `s1`, `s2`, … */
export function newSectionId(sections: Section[]): string {
  const used = new Set(sections.map((section) => section.section_id));
  let n = sections.length + 1;
  while (used.has(`s${n}`)) n += 1;
  return `s${n}`;
}

/** Every card id of the report's sections, so a new card gets a fresh one. */
function cardsOf(sections: Section[]): Card[] {
  return sections.flatMap((section) => (section.card ? [section.card] : []));
}

export function newSection(kind: SectionKind, sections: Section[]): Section {
  const base: Section = { section_id: newSectionId(sections), kind, title: "", text: "", card: null, events: null, width: "full" };
  if (kind === "card") return { ...base, card: { ...defaultCard("trend", cardsOf(sections)), height: 3 } };
  if (kind === "events") return { ...base, title: t("Events"), events: { kinds: [], limit: 20 } };
  if (kind === "text") return { ...base, text: "## " };
  if (kind === "assistant") return { ...base, title: t("By the assistant"), assistant: { asset_ids: [], children: true, analyses: ["loops"], requirements: "", version: 1 } };
  return base;
}

/** The sections with one moved `by` places (-1 earlier, 1 later). */
export function moveSection(sections: Section[], sectionId: string, by: number): Section[] {
  const at = sections.findIndex((section) => section.section_id === sectionId);
  const to = at + by;
  if (at < 0 || to < 0 || to >= sections.length) return sections;
  const next = [...sections];
  const [moved] = next.splice(at, 1);
  next.splice(to, 0, moved);
  return next;
}

/** The sections with `section` put at `at` (null: at the end). */
export function insertSection(sections: Section[], section: Section, at: number | null): Section[] {
  if (at === null || at >= sections.length) return [...sections, section];
  return [...sections.slice(0, Math.max(at, 0)), section, ...sections.slice(Math.max(at, 0))];
}

export function replaceSection(sections: Section[], section: Section): Section[] {
  return sections.some((item) => item.section_id === section.section_id)
    ? sections.map((item) => (item.section_id === section.section_id ? section : item))
    : [...sections, section];
}

/** What a section is called in the editor's list. */
export function sectionName(section: Section): string {
  if (section.kind === "card") return section.card?.title || t("Panel");
  if (section.kind === "break") return t("Page break");
  if (section.kind === "text") return (section.text.split("\n").find((line) => line.trim()) ?? "").replace(/^#+\s*/, "").slice(0, 60) || t("Text");
  return section.title || t(SECTION_LABELS[section.kind]);
}

/** A heading of a text cell: the report's outline, as the side navigation lists it. */
export interface OutlineEntry { sectionId: string; level: number; text: string; nth: number }

/** The headings (`#` to `####`) of the text cells, in order, outside code blocks, as
 * `renderMarkdown` draws them; `nth` counts the headings within their cell. */
export function outlineOf(sections: Section[]): OutlineEntry[] {
  const found: OutlineEntry[] = [];
  for (const section of sections) {
    if (section.kind !== "text") continue;
    let code = false;
    let nth = 0;
    for (const line of section.text.replaceAll("\r\n", "\n").split("\n")) {
      if (line.startsWith("```")) { code = !code; continue; }
      const heading = code ? null : /^(#{1,4})\s+(.+?)\s*#*\s*$/.exec(line);
      if (!heading) continue;
      found.push({ sectionId: section.section_id, level: heading[1].length, text: heading[2].replace(/\*\*|__|`/g, ""), nth });
      nth += 1;
    }
  }
  return found;
}

/** A text section of before the cells (a heading above its Markdown) as one cell. */
export function textCell(section: Section): Section {
  if (section.kind !== "text" || !section.title.trim()) return section;
  return { ...section, title: "", text: `# ${section.title.trim()}${section.text ? `\n\n${section.text}` : ""}` };
}

/** The editable copy of a saved report. */
export function reportDraftOf(report: Partial<ReportDraft>): ReportDraft {
  return {
    name: report.name ?? "", description: report.description ?? "", folder_id: report.folder_id ?? "",
    period: report.period ?? "24h", schedule: { ...EMPTY_SCHEDULE, ...(report.schedule ?? {}) },
    recipients: [...(report.recipients ?? [])], email: Boolean(report.email),
    sections: (report.sections ?? []).map((section) => textCell({ ...section })),
  };
}

/** The period the report covers when made now, from its end back. */
export function periodRange(period: string, end: Date = new Date()): { start: Date; end: Date } {
  const match = /^(\d+)([smhd])$/.exec(period);
  const seconds = match ? Number(match[1]) * { s: 1, m: 60, h: 3600, d: 86400 }[match[2] as "s"]! : 86400;
  return { start: new Date(end.getTime() - seconds * 1000), end };
}

export const TRIGGER_LABELS: Record<ReportRun["trigger"], string> = { schedule: "Scheduled", send: "Send now", download: "Download" };

/** How a run went, as a state the suite colours: sent in full, with sections missing, or failed. */
export function runState(run: ReportRun): "ok" | "warning" | "alarm" | "unknown" {
  if (run.status === "failed") return "alarm";
  if (run.status === "running") return "unknown";
  return run.problems ? "warning" : "ok";
}

export function runStatusLabel(run: ReportRun): string {
  if (run.status === "failed") return t("Failed");
  if (run.status === "running") return t("Making…");
  if (run.problems) return run.problems === 1 ? t("1 section not read") : t("{n} sections not read", { n: run.problems });
  return run.trigger === "download" ? t("Made") : t("Sent");
}

/** "3 of 4": the people a send reached, of those it went to (none for a download). */
export function deliveredLabel(run: ReportRun): string {
  if (run.trigger === "download") return t("Nobody (download)");
  if (run.status !== "done") return "—";
  return run.delivered === 1 ? t("1 person") : t("{n} people", { n: run.delivered });
}

export function pdfSize(bytes: number): string {
  if (!bytes) return "—";
  return bytes < 1024 * 1024 ? t("{n} KB", { n: Math.max(1, Math.round(bytes / 1024)) }) : t("{n} MB", { n: (bytes / 1024 / 1024).toFixed(1) });
}
