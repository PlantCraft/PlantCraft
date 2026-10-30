/**
 * When a schedule runs, as its form holds it: once, or every N minutes,
 * hours, days, weeks or months, on some weekdays, between two times, from a first to a last day.
 * The server keeps the plain cadences (every N minutes, daily, weekly) where they say it all and a
 * calendar (``linkcraft.engine.recurrence``) for the rest, so older schedules stay as they were.
 */
import type { Recurrence, Schedule } from "./types";

export const FREQUENCIES = ["once", "minutes", "hours", "days", "weeks", "months"] as const;
export type Frequency = (typeof FREQUENCIES)[number] | "interval";
export const WEEKDAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export type When = {
  freq: Frequency; every: number; interval_minutes: number; times: string[]; weekdays: number[];
  between: boolean; between_from: string; between_to: string;
  month_mode: "day" | "weekday"; month_day: number; month_n: number; month_weekday: number;
  start: string; end: string; scheduled_for: string;
};

export const BLANK_WHEN: When = {
  freq: "days", every: 1, interval_minutes: 60, times: ["06:00"], weekdays: [], between: false, between_from: "06:00", between_to: "18:00",
  month_mode: "day", month_day: 1, month_n: 1, month_weekday: 0, start: "", end: "", scheduled_for: "",
};

type Timing = Pick<Schedule, "cadence" | "interval_minutes" | "time_local" | "weekday" | "scheduled_for" | "recurrence">;

/** A saved schedule's timing in the form's terms. */
export function whenOf(schedule: Timing): When {
  const base = { ...BLANK_WHEN, scheduled_for: schedule.scheduled_for ?? "" };
  const at = schedule.time_local ?? "08:00";
  const rule = schedule.recurrence;
  if (schedule.cadence === "calendar" && rule) {
    return {
      ...base, freq: rule.freq, every: rule.every ?? 1, times: rule.times?.length ? rule.times : ["08:00"], weekdays: rule.weekdays ?? [],
      between: Boolean(rule.between), between_from: rule.between?.[0] ?? "06:00", between_to: rule.between?.[1] ?? "18:00",
      month_mode: rule.month_weekday ? "weekday" : "day", month_day: rule.month_day ?? 1,
      month_n: rule.month_weekday?.n ?? 1, month_weekday: rule.month_weekday?.weekday ?? 0,
      start: rule.start ?? "", end: rule.end ?? "",
    };
  }
  if (schedule.cadence === "once") return { ...base, freq: "once" };
  if (schedule.cadence === "interval") {
    const minutes = Number(schedule.interval_minutes ?? 60);
    // Less than a minute, or not a whole one: kept as it is (the signal round every 30 s, say).
    if (!Number.isInteger(minutes) || minutes < 1) return { ...base, freq: "interval", interval_minutes: minutes };
    return minutes % 60 === 0 && minutes <= 24 * 60 ? { ...base, freq: "hours", every: minutes / 60 } : { ...base, freq: "minutes", every: minutes };
  }
  if (schedule.cadence === "hourly") return { ...base, freq: "hours", every: 1, between: true, between_from: `00:${at.slice(3)}`, between_to: "23:59" };
  if (schedule.cadence === "weekly") return { ...base, freq: "weeks", weekdays: [schedule.weekday ?? 0], times: [at] };
  return { ...base, freq: "days", times: [at] };
}

/** The rule the form describes, as the server checks it. */
export function recurrenceOf(when: When): Recurrence {
  const rule: Recurrence = { freq: when.freq as Recurrence["freq"], every: Math.max(1, Math.round(Number(when.every) || 1)) };
  if (["minutes", "hours"].includes(when.freq)) {
    if (when.between) rule.between = [when.between_from, when.between_to];
  } else {
    rule.times = Array.from(new Set(when.times.filter(Boolean))).sort();
  }
  if (when.weekdays.length && when.freq !== "months") rule.weekdays = [...when.weekdays].sort();
  if (when.freq === "months") {
    if (when.month_mode === "weekday") rule.month_weekday = { n: when.month_n as 1 | 2 | 3 | 4 | -1, weekday: when.month_weekday };
    else rule.month_day = when.month_day;
  }
  if (when.start) rule.start = when.start;
  if (when.end) rule.end = when.end;
  return rule;
}

/** The timing fields of a schedule's request: the plain cadence when it says it all, a calendar otherwise. */
export function timingOf(when: When): Record<string, unknown> {
  const none = { interval_minutes: null, time_local: null, weekday: null, scheduled_for: null, recurrence: null };
  if (when.freq === "once") return { ...none, cadence: "once", scheduled_for: when.scheduled_for || null };
  if (when.freq === "interval") return { ...none, cadence: "interval", interval_minutes: Number(when.interval_minutes) };
  const every = Math.max(1, Math.round(Number(when.every) || 1));
  const dated = Boolean(when.start || when.end);
  const step = when.freq === "hours" ? every * 60 : when.freq === "minutes" ? every : null;
  const times = Array.from(new Set(when.times.filter(Boolean)));
  if (step && !dated && !when.weekdays.length) {
    if (!when.between) return { ...none, cadence: "interval", interval_minutes: step };
    if (when.freq === "hours" && every === 1 && when.between_from.startsWith("00:") && when.between_to === "23:59") {
      return { ...none, cadence: "hourly", time_local: when.between_from };
    }
  }
  if (when.freq === "days" && every === 1 && times.length === 1 && !when.weekdays.length && !dated) return { ...none, cadence: "daily", time_local: times[0] };
  if (when.freq === "weeks" && every === 1 && times.length === 1 && when.weekdays.length === 1 && !dated) {
    return { ...none, cadence: "weekly", time_local: times[0], weekday: when.weekdays[0] };
  }
  // A calendar every N minutes or hours names its step too: results expire after two of them.
  return { ...none, cadence: "calendar", interval_minutes: step, recurrence: recurrenceOf(when) };
}

/** What the form misses before it can be saved, or "" (the server says the rest). */
export function whenProblem(when: When): string {
  if (when.freq === "once") return when.scheduled_for ? "" : "Choose the date and time of the one-off run.";
  if (["days", "weeks", "months"].includes(when.freq) && !when.times.filter(Boolean).length) return "Choose at least one time of day.";
  if (when.freq === "weeks" && !when.weekdays.length) return "Choose the days of the week it runs.";
  if (when.between && when.between_from > when.between_to) return "The start of the time span comes after its end.";
  if (when.start && when.end && when.end < when.start) return "The last day comes before the first.";
  return "";
}
