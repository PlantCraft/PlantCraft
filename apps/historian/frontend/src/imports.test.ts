import { describe, expect, it } from "vitest";
import { repeatLine } from "./ImportsPage";

describe("imports that repeat from a folder", () => {
  it("say how often and from where", () => {
    const repeat = { pattern: "/csv/lab/*.csv", check_minutes: 1440, by: "ana", checked_ms: null, files: 0, problem: "" };
    expect(repeatLine(repeat)).toBe("Repeats every day from /csv/lab/*.csv");
    expect(repeatLine({ ...repeat, check_minutes: 60 })).toBe("Repeats every hour from /csv/lab/*.csv");
    expect(repeatLine({ ...repeat, check_minutes: 90 })).toBe("Repeats every 90 minutes from /csv/lab/*.csv");
  });
});
