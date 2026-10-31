import { describe, expect, it } from "vitest";
import { localToIso, noteWindow } from "./PointNotes";

describe("notes", () => {
  it("reads a relative period up to now and a fixed one as it is", () => {
    const now = Date.parse("2026-10-31T12:00:00Z");
    expect(noteWindow({ window: "1h", from: "", to: "" }, now)).toEqual({ start: "2026-10-31T11:00:00.000Z", end: "2026-10-31T12:00:00.000Z" });
  });
  it("turns a local time into UTC and leaves empty empty", () => {
    expect(localToIso("")).toBe("");
    expect(localToIso("2026-10-31T12:00")).toBe(new Date("2026-10-31T12:00").toISOString());
  });
});
