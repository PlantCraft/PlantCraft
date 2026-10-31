import { describe, expect, it } from "vitest";
import { executionDetail } from "./ExecutionsPage";
import { cadenceText, DEFAULT_RETRY, keepOf, keepOptions, keepValue, outputsCost, ownerRef, parameterSource, payloadOf, priorityLabel, sizeText } from "./SchedulesPage";
import { BLANK_WHEN, timingOf, whenOf, whenProblem } from "./scheduleWhen";
import type { Execution, RecordedOutput } from "./types";

const FORM = {
  name: " Night run ", profile_id: "", owner: "ana", mode: "list" as const, ids: "FIC-101, LIC-102\nTIC-104", assets: [] as string[], q: "", allAssets: false,
  when: { ...BLANK_WHEN, freq: "days" as const, times: ["00:00"] }, timezone: "America/Sao_Paulo",
  lookback_minutes: 1440, priority: 20, spread_minutes: 30, enabled: true, retry: DEFAULT_RETRY, outputs: {}, node_parameters: {},
};

describe("schedules", () => {
  it("says when a schedule runs in plain words", () => {
    expect(cadenceText({ cadence: "interval", interval_minutes: 10 })).toBe("every 10 min");
    expect(cadenceText({ cadence: "interval", interval_minutes: 0.5 })).toBe("every 30 s");
    expect(cadenceText({ cadence: "daily", time_local: "00:00" })).toBe("daily at 00:00");
    expect(cadenceText({ cadence: "weekly", time_local: "06:30", weekday: 0 })).toBe("Monday at 06:30");
    expect(cadenceText({ cadence: "hourly", time_local: "00:15" })).toBe("every hour at :15");
    expect(cadenceText({ cadence: "calendar", when: "Every 15 minutes, Mon to Fri" })).toBe("Every 15 minutes, Mon to Fri");
  });

  it("sends only what the frequency uses", () => {
    const daily = payloadOf(FORM);
    expect(daily).toMatchObject({ name: "Night run", cadence: "daily", time_local: "00:00", interval_minutes: null, weekday: null, priority: 20, spread_minutes: 30 });
    expect(daily.selector).toEqual({ mode: "list", ids: ["FIC-101", "LIC-102", "TIC-104"] });
    const every = payloadOf({ ...FORM, when: { ...FORM.when, freq: "hours" }, mode: "all" });
    expect(every).toMatchObject({ cadence: "interval", interval_minutes: 60, time_local: null, recurrence: null, selector: { mode: "all" } });
    expect(daily.retry).toEqual({ enabled: true, count: 2, wait_minutes: 5, abort_on_next: true });
    expect(payloadOf({ ...FORM, mode: "filter", q: " FIC " }).selector).toEqual({ mode: "filter", q: "FIC" });
    // An algorithm on assets runs on the assets chosen, whatever the loop fields say.
    expect(payloadOf({ ...FORM, assets: ["u-100-furnaces"] }, true).selector).toEqual({ mode: "list", ids: ["u-100-furnaces"] });
    // Every asset of the algorithm (its own and those of its equipment types, A20).
    expect(payloadOf({ ...FORM, assets: ["u-100-furnaces"], allAssets: true }, true).selector).toEqual({ mode: "all" });
    // An empty data window is Analytics' default: not sent (the API refuses 0, and the loop
    // monitor's page answered every preview and save with 422).
    expect(payloadOf(FORM).lookback_minutes).toBe(1440);
    expect(payloadOf({ ...FORM, lookback_minutes: 0 }).lookback_minutes).toBeUndefined();
  });

  it("sends the recorded outputs of an algorithm on assets only", () => {
    const outputs = { health: { record: false } };
    expect(payloadOf({ ...FORM, outputs }).outputs).toBeUndefined();
    expect(payloadOf({ ...FORM, outputs, assets: ["furnace"] }, true).outputs).toEqual(outputs);
  });

  it("offers how long each kind of output is kept and says what it costs", () => {
    expect(keepOptions("series").map((item) => item.value)).toEqual(["runs:1", "runs:3", "runs:10", "runs:30", "runs:100"]);
    const single = keepOptions("verdict", { days: 45 });
    expect(single[0]).toEqual({ value: "forever", label: "Forever" });
    expect(single.find((item) => item.value === "days:730")?.label).toBe("2 years");
    expect(single.at(-1)).toEqual({ value: "days:45", label: "45 days" });
    for (const keep of [{ forever: true }, { days: 400 }, { runs: 10 }]) expect(keepOf(keepValue(keep))).toEqual(keep);
    expect([512, 3400, 12_000_000, 1_234_000_000].map(sizeText)).toEqual(["512 B", "3.4 kB", "12 MB", "1.2 GB"]);
    const row = (change: Partial<RecordedOutput>): RecordedOutput => ({
      key: "x", name: "X", kind: "number", unit: "", description: "", values_per_run: 1, record: true, keep: { days: 400 },
      values_per_day: 96, stored_values: 38_400, stored_bytes: 230_400, grows: false, ...change,
    });
    expect(outputsCost([row({}), row({ record: false }), row({ grows: true })], 3)).toEqual({ perDay: 576, bytes: 1_382_400, grows: true });
  });

  it("keeps the plain cadences where they say it all and a calendar for the rest", () => {
    const when = { ...BLANK_WHEN };
    expect(timingOf({ ...when, freq: "minutes", every: 15 })).toMatchObject({ cadence: "interval", interval_minutes: 15, recurrence: null });
    expect(timingOf({ ...when, freq: "weeks", weekdays: [2], times: ["06:30"] })).toMatchObject({ cadence: "weekly", weekday: 2, time_local: "06:30" });
    expect(timingOf({ ...when, freq: "hours", between: true, between_from: "00:15", between_to: "23:59" })).toMatchObject({ cadence: "hourly", time_local: "00:15" });
    expect(timingOf({ ...when, freq: "once", scheduled_for: "2026-11-02T06:00" })).toMatchObject({ cadence: "once", scheduled_for: "2026-11-02T06:00" });
    const office = timingOf({ ...when, freq: "minutes", every: 15, weekdays: [4, 0, 1, 2, 3], between: true });
    expect(office).toMatchObject({ cadence: "calendar", interval_minutes: 15, time_local: null });
    expect(office.recurrence).toEqual({ freq: "minutes", every: 15, between: ["06:00", "18:00"], weekdays: [0, 1, 2, 3, 4] });
    const monthly = timingOf({ ...when, freq: "months", month_mode: "weekday", month_n: -1, month_weekday: 4, times: ["18:00", "06:00", "06:00"], end: "2027-06-30" });
    expect(monthly).toMatchObject({ cadence: "calendar", interval_minutes: null });
    expect(monthly.recurrence).toEqual({ freq: "months", every: 1, times: ["06:00", "18:00"], month_weekday: { n: -1, weekday: 4 }, end: "2027-06-30" });
  });

  it("reads a saved schedule back into the form", () => {
    expect(whenOf({ cadence: "interval", interval_minutes: 0.5 })).toMatchObject({ freq: "interval", interval_minutes: 0.5 });
    expect(whenOf({ cadence: "interval", interval_minutes: 120 })).toMatchObject({ freq: "hours", every: 2 });
    expect(whenOf({ cadence: "weekly", weekday: 3, time_local: "07:00" })).toMatchObject({ freq: "weeks", weekdays: [3], times: ["07:00"] });
    const rule = { freq: "days" as const, every: 2, times: ["06:00"], start: "2026-11-02" };
    const back = whenOf({ cadence: "calendar", recurrence: rule });
    expect(back).toMatchObject({ freq: "days", every: 2, times: ["06:00"], start: "2026-11-02", end: "" });
    expect(timingOf(back).recurrence).toEqual(rule);
  });

  it("says what the form misses before it is saved", () => {
    expect(whenProblem({ ...BLANK_WHEN, freq: "weeks", weekdays: [] })).toBe("Choose the days of the week it runs.");
    expect(whenProblem({ ...BLANK_WHEN, freq: "once" })).toBe("Choose the date and time of the one-off run.");
    expect(whenProblem({ ...BLANK_WHEN, start: "2026-11-02", end: "2026-11-01" })).toBe("The last day comes before the first.");
    expect(whenProblem(BLANK_WHEN)).toBe("");
  });

  it("names owners as the suite does", () => {
    expect(["ana", "user:ana", "group:on-call", "", null].map(ownerRef)).toEqual(["user:ana", "user:ana", "group:on-call", "", ""]);
  });

  it("names the queue's priorities", () => {
    expect([80, 50, 20, 33].map(priorityLabel)).toEqual(["High", "Normal", "Low", "Normal"]);
  });

  it("says how far an execution got, its tries and when it may start", () => {
    const base = { status: "running", progress: { done: 12, total: 50 }, attempts: 1, due_at: null } as unknown as Execution;
    expect(executionDetail(base)).toBe("12 of 50");
    expect(executionDetail({ ...base, status: "queued", progress: null, attempts: 2 })).toBe("try 2");
    expect(executionDetail({ ...base, status: "running", progress: null, attempts: 2, max_attempts: 3 })).toBe("try 2 of 3");
    expect(executionDetail({ ...base, status: "failed", attempts: 3, error: "PlantCraft cannot be reached" })).toBe("After 3 tries: PlantCraft cannot be reached");
    expect(executionDetail({ ...base, status: "failed", attempts: 1, error: "broken" })).toBe("");
  });
});

describe("a monitor's parameters", () => {
  it("say where each value comes from: the monitor, then the algorithm, then the block", () => {
    expect(parameterSource(2, 3)).toBe("monitor");
    expect(parameterSource(2, undefined)).toBe("algorithm");
    expect(parameterSource(undefined, undefined)).toBe("block");
  });
  it("go in the body of a monitor on assets only", () => {
    const form = { ...FORM, node_parameters: { dev: { limit: 3 } } };
    expect(payloadOf(form, true).node_parameters).toEqual({ dev: { limit: 3 } });
    expect(payloadOf(form, false).node_parameters).toBeUndefined();
  });
});
