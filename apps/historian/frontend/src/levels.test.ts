import { describe, expect, it } from "vitest";
import { compression, effective, override, ownerList, forecastLine, profileOf, rangeNote } from "./levels";

describe("settings levels", () => {
  it("says the value in effect and where it comes from", () => {
    expect(effective(400, "days", "general")).toBe("400 days, from general settings");
    expect(effective(5, "s", "source")).toBe("5 s, from the source");
    expect(effective(0.25, "", "point")).toBe("0.25, set on this signal");
    expect(effective(0, "days", "point")).toBe("forever, set on this signal");
  });
  it("names the compression of a point without a range as a share of its value", () => {
    expect(compression({ kind: "number", deviation: 0, deviation_percent: 0.1, unit: "m3/h" })).toBe("± 0.1 % of the value");
    expect(compression({ kind: "number", deviation: 0.2, deviation_percent: null, unit: "bar" })).toBe("± 0.2 bar");
    expect(compression({ kind: "number", deviation: 0, deviation_percent: null, unit: "" })).toBe("every change");
    expect(compression({ kind: "text", deviation: 0, unit: "" })).toBe("every change");
  });
  it("reads an empty override as inherited", () => {
    expect(override("")).toBeNull();
    expect(override("  ")).toBeNull();
    expect(override(undefined)).toBeNull();
    expect(override("30")).toBe(30);
  });
  it("says the exception first and picks the profile a point shows", () => {
    expect(compression({ kind: "number", deviation: 0.4, deviation_percent: null, exception: 0.2, exception_percent: null, unit: "bar" })).toBe("exception ± 0.2 bar, ± 0.4 bar");
    expect(profileOf({ profile: "fine", own: { deviation: null, exception: null } })).toBe("fine");
    expect(profileOf({ profile: "", own: { deviation: 1, exception: null } })).toBe("custom");
    expect(profileOf({ profile: "", own: { deviation: null, exception: null } })).toBe("");
  });
});

describe("rangeNote", () => {
  it("says where a range comes from, and asks to confirm a suggestion", () => {
    expect(rangeNote("source")).toContain("server");
    expect(rangeNote("suggested")).toContain("confirm");
    expect(rangeNote("")).toContain("after a day");
    expect(rangeNote(undefined)).toBe(rangeNote(""));
  });
});

describe("forecastLine", () => {
  const base = { bytes_per_day: 1, bytes_per_year: 13 * 1024 ** 3, free_bytes: 500 * 1024 ** 3, alert_days: 90, at: 0 };
  it("says the growth a year and when the disk fills, in years or days", () => {
    expect(forecastLine({ ...base, days_to_full: 365 * 4 }).text).toContain("4 years");
    const soon = forecastLine({ ...base, days_to_full: 42.5 });
    expect(soon.text).toContain("42 days");
    expect(soon.warn).toBe(true);
    expect(forecastLine({ ...base, days_to_full: null }).text).toContain("stops before");
    expect(forecastLine({ ...base, free_bytes: null, days_to_full: null }).text).toContain("not known");
  });
});

describe("source owners", () => {
  it("reads typed owners as user and group references", () => {
    expect(ownerList("Ana, group:automation;  user:bruno")).toEqual(["user:ana", "group:automation", "user:bruno"]);
    expect(ownerList("  ")).toEqual([]);
  });
});
