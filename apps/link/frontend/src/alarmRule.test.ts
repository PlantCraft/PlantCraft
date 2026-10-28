import { describe, expect, it } from "vitest";
import { alarmRuleHref } from "./SchedulesPage";

describe("a schedule's alarm rule", () => {
  it("opens the Alarms app's new rule filled in for the schedule", () => {
    expect(alarmRuleHref("abc-1", "PV & valve")).toBe("/alarm/rules/new?schedule=abc-1&name=PV+%26+valve");
  });
});
