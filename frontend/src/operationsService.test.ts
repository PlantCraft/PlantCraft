import { describe, expect, it } from "vitest";
import { currentTarget, minutesText, slaText, workingHoursText } from "./OperationsRequests";
import { grantState, readGrantPrefill } from "./OperationsSupport";
import { uptimeText, uptimeTone, windowState } from "./OperationsUptime";
import type { SlaClock } from "./collabApi";

const clock = (changes: Partial<SlaClock>): SlaClock => ({ target_minutes: 240, used_minutes: 60, state: "running", due_at: null, ...changes });

describe("Operations, targets and support access", () => {
  it("reads a target as time left, late or met", () => {
    expect(slaText(clock({}))).toEqual({ text: "3 h left", tone: "" });
    expect(slaText(clock({ used_minutes: 200, state: "at_risk" }))?.tone).toBe("warn");
    expect(slaText(clock({ used_minutes: 300, state: "breached" }))).toEqual({ text: "late by 1 h", tone: "bad" });
    expect(slaText(clock({ state: "met" }))?.tone).toBe("good");
    expect(slaText(clock({ paused: true }))?.text).toBe("paused · 3 h left");
    expect(slaText(null)).toBeNull();
    expect(minutesText(3 * 1440)).toBe("3 days");
  });

  it("follows the first answer until there is one, then the resolution", () => {
    const sla = { response: clock({}), resolution: clock({ target_minutes: 1440 }) };
    expect(currentTarget({ sla, first_response_at: null })?.label).toBe("First answer");
    expect(currentTarget({ sla, first_response_at: "2026-10-31T10:00:00Z" })?.clock.target_minutes).toBe(1440);
    expect(currentTarget({ sla: null, first_response_at: null })).toBeNull();
  });

  it("says when support access ends, and opens the form from a request", () => {
    const now = Date.parse("2026-10-31T10:00:00Z");
    expect(grantState({ active: true, ends_at: "2026-10-31T14:00:00Z", ended_at: null }, now)).toEqual({ text: "ends in 4 h", active: true });
    expect(grantState({ active: false, ends_at: "2026-10-31T09:00:00Z", ended_at: "2026-10-31T09:00:00Z" }, now).text).toMatch(/^ended early/);
    expect(readGrantPrefill("?new=1&request=12&user=ana")).toEqual({ username: "ana", request: "12" });
    expect(readGrantPrefill("?x=1")).toBeNull();
  });

  it("writes a queue's working hours", () => {
    expect(workingHoursText({ days: ["mon", "tue", "wed", "thu", "fri"], start: "08:00", end: "17:00" })).toBe("Mon–Fri 08:00–17:00");
    expect(workingHoursText({ days: ["sat", "mon"], start: "06:00", end: "14:00" })).toBe("Mon, Sat 06:00–14:00");
  });
});

describe("Operations, uptime", () => {
  it("reads uptime and maintenance windows", () => {
    expect(uptimeText(100)).toBe("100 %");
    expect(uptimeText(99.5)).toBe("99.50 %");
    expect(uptimeText(null)).toBe("—");
    expect(uptimeTone(98.2)).toBe("warn");
    expect(uptimeTone(90)).toBe("bad");
    const now = Date.parse("2026-10-31T12:00:00Z");
    expect(windowState({ starts_at: "2026-10-31T13:00:00Z", ends_at: "2026-10-31T15:00:00Z", ended_at: null }, now)).toBe("planned");
    expect(windowState({ starts_at: "2026-10-31T11:00:00Z", ends_at: "2026-10-31T15:00:00Z", ended_at: null }, now)).toBe("active");
    expect(windowState({ starts_at: "2026-10-31T11:00:00Z", ends_at: "2026-10-31T15:00:00Z", ended_at: "2026-10-31T11:30:00Z" }, now)).toBe("ended");
  });
});
