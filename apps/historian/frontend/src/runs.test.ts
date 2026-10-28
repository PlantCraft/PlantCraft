import { describe, expect, it } from "vitest";
import { runLines, runPick } from "./RunsTrend";

describe("runs trend", () => {
  it("reads the newest run, the newest few, or one run", () => {
    expect(runPick("latest")).toEqual({ runs: 1 });
    expect(runPick("last:5")).toEqual({ runs: 5 });
    expect(runPick("2026-10-19T04:30:00+00:00")).toEqual({ run: "2026-10-19T04:30:00+00:00" });
  });
  it("draws each run as its own line, the older ones dotted", () => {
    const lines = runLines({ signal: "s", kind: "runs", runs: [
      { run_at: "2026-10-19T04:30:00+00:00", t: ["2026-10-19T04:00:00+00:00"], v: [1] },
      { run_at: "2026-10-19T03:30:00+00:00", t: ["2026-10-19T03:00:00+00:00"], v: [2] },
    ] }, "%");
    expect(lines.map((line) => line.dash)).toEqual([undefined, "dot"]);
    expect(lines[0].name).toMatch(/^Run of /);
  });
});
