import { describe, expect, it } from "vitest";
import { answerPhase, splitByDefault, trendsHref } from "./AssistantAnswer";

const working = (steps: Array<{ tool: string; title: string; state: "running" | "ok" | "error" }>, text = "", queued = false) => ({ state: "working" as const, text, steps, meta: { queued } });

describe("an answer being written", () => {
  it("says what it is doing now", () => {
    expect(answerPhase(working([], "", true))).toBe("Waiting for a free slot…");
    expect(answerPhase(working([]))).toBe("Thinking…");
    expect(answerPhase(working([{ tool: "search_signals", title: "Search signals", state: "running" }]))).toBe("Reading: Search signals…");
    expect(answerPhase(working([{ tool: "show_chart", title: "Draw a chart", state: "running" }]))).toBe("Drawing the chart…");
    expect(answerPhase(working([{ tool: "propose_create", title: "Prepare the card", state: "running" }]))).toBe("Preparing the card…");
    expect(answerPhase(working([{ tool: "search_signals", title: "Search signals", state: "ok" }]))).toBe("Thinking about what it read…");
    // The text shows itself as it comes; a finished answer says nothing.
    expect(answerPhase(working([], "FIC-101 is"))).toBeNull();
    expect(answerPhase({ state: "done", text: "x", steps: [] })).toBeNull();
  });
});

describe("an answer's chart", () => {
  const series = (signal: string, v: number[], unit = "") => ({ signal, unit, t: v.map((_, i) => `2026-10-26T0${i}:00:00Z`), v });
  it("draws far-apart signals on their own plots", () => {
    expect(splitByDefault([series("FIC-101.PV", [290, 310]), series("FIC-101.SP", [300, 300])])).toBe(false);
    expect(splitByDefault([series("FIC-101.PV", [290, 310]), series("FIC-101.MODE", [0, 1])])).toBe(true);
    expect(splitByDefault([series("A", [1, 2], "m3/h"), series("B", [1, 2], "%")])).toBe(true);
    expect(splitByDefault([series("A", [1, 2])])).toBe(false);
  });
  it("goes on in Trends on the platform's host", () => {
    const chart = { title: "", start: "", end: "", series: [], trends: "/dash/trends?signal=A" };
    expect(trendsHref(chart)).toBe("/dash/trends?signal=A");
    expect(trendsHref(chart, "https://plant.example/")).toBe("https://plant.example/dash/trends?signal=A");
    expect(trendsHref({ ...chart, trends: null })).toBeNull();
  });
});
