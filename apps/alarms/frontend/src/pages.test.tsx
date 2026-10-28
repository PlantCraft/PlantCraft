import { describe, expect, it } from "vitest";
import { NAV } from "./pages";

describe("navigation", () => {
  it("in the order things happen: Overview (with performance), Events (each event), Rules (with the silences), Alarms (each alarm, the asset deep link)", () => {
    const [overview, events, rules, alarms] = NAV;
    expect(NAV.map((item) => item.to)).toEqual(["/", "/events", "/rules", "/alarms"]);
    expect(overview.match?.("/")).toBe(true);
    expect(overview.match?.("/performance")).toBe(true);
    expect(overview.match?.("/targets")).toBe(true);
    expect(overview.match?.("/alarms")).toBe(false);
    expect(alarms.match?.("/alarms/fic-101-high")).toBe(true);
    expect(alarms.match?.("/assets/FIC-101")).toBe(true);
    expect(alarms.match?.("/history")).toBe(true);
    expect(events.match?.("/events")).toBe(true);
    expect(events.match?.("/events/42")).toBe(true);
    expect(rules.match?.("/silences")).toBe(true);
    expect(rules.match?.("/rules/new")).toBe(true);
  });
});
