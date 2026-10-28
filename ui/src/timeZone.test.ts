import { afterEach, describe, expect, it } from "vitest";
import { formatDate } from "./format";
import { isoOf, localOf } from "./timeChart";
import { cityName, configureTimeZone, displayStamp, displayTimeZone, fileStamp, fileTime, fileTimeHeader, fixedOffsetZones, fromWallClock, isFixedOffset, LOCAL_ZONE, offsetLabel, resolveTimeZone, timeZoneLabel, wallClock, zonedFigure } from "./timeZone";
import { timeZoneGroups, timeZoneValue } from "./TimeZoneSelect";

const NOON_UTC = Date.parse("2026-10-23T15:00:00Z");

describe("display time zone", () => {
  afterEach(() => configureTimeZone({ plant: null, mode: null }));

  it("is UTC until the platform names the plant's zone", () => {
    expect(wallClock(NOON_UTC)).toBe("2026-10-23 15:00:00.000");
    expect(formatDate("2026-10-23T15:00:00Z")).toMatch(/3:00\sPM UTC$/);
  });

  it("shows UTC times as the plant's wall clock and reads them back", () => {
    configureTimeZone({ plant: "America/Sao_Paulo", mode: "plant" });
    expect(wallClock(NOON_UTC)).toBe("2026-10-23 12:00:00.000");
    expect(fromWallClock("2026-10-23T12:00")).toBe(NOON_UTC);
    expect(formatDate("2026-10-23T15:00:00Z")).toMatch(/12:00\sPM$/);
    expect(formatDate("2026-10-23T15:00:00Z", { dateStyle: "medium" })).toBe("Oct 23, 2026");
    expect(localOf("2026-10-23T15:00:00Z")).toBe("2026-10-23T12:00");
    expect(isoOf("2026-10-23T12:00")).toBe("2026-10-23T15:00:00.000Z");
  });

  it("crosses a daylight-saving change", () => {
    configureTimeZone({ plant: "Europe/Berlin", mode: "plant" });
    expect(wallClock(Date.parse("2026-10-25T00:30:00Z"))).toBe("2026-10-25 02:30:00.000");
    expect(wallClock(Date.parse("2026-10-25T01:30:00Z"))).toBe("2026-10-25 02:30:00.000");
    expect(wallClock(Date.parse("2026-07-01T12:00:00Z"))).toBe("2026-07-01 14:00:00.000");
    expect(new Date(fromWallClock("2026-07-01 14:00:00")).toISOString()).toBe("2026-07-01T12:00:00.000Z");
  });

  it("moves a Plotly figure's UTC times and leaves the rest alone", () => {
    configureTimeZone({ plant: "America/Sao_Paulo", mode: "plant" });
    const figure = zonedFigure({
      data: [{ x: ["2026-10-23T15:00:00Z", "2026-10-23T16:00:00+00:00"], y: [1, 2] }, { x: [1, 2], y: [3, 4] }, { x: ["2026-10-23 15:00"], y: [5] }],
      layout: { xaxis: { range: ["2026-10-23T15:00:00Z", "2026-10-23T16:00:00Z"] }, shapes: [{ x0: "2026-10-23T15:00:00Z", x1: "2026-10-23T15:30:00Z" }] },
    });
    expect((figure.data?.[0] as { x: string[] }).x).toEqual(["2026-10-23 12:00:00.000", "2026-10-23 13:00:00.000"]);
    expect((figure.data?.[1] as { x: number[] }).x).toEqual([1, 2]);
    expect((figure.data?.[2] as { x: string[] }).x).toEqual(["2026-10-23 15:00"]);
    expect((figure.layout?.xaxis as { range: string[] }).range[0]).toBe("2026-10-23 12:00:00.000");
    expect((figure.layout?.shapes as Array<{ x1: string }>)[0].x1).toBe("2026-10-23 12:30:00.000");
    expect(displayStamp(42)).toBe(42);
  });

  it("follows the device when the person picks it", () => {
    configureTimeZone({ plant: "America/Sao_Paulo", mode: "device" });
    const device = Intl.DateTimeFormat().resolvedOptions().timeZone;
    expect(wallClock(NOON_UTC)).toBe(wallClock(NOON_UTC, device));
  });
});

describe("time zone picker", () => {
  afterEach(() => configureTimeZone({ plant: null, mode: null }));

  it("names zones by their offset from UTC", () => {
    expect(offsetLabel("UTC")).toBe("UTC");
    expect(offsetLabel("Etc/GMT+3")).toBe("UTC−3");
    expect(offsetLabel("Etc/GMT-14")).toBe("UTC+14");
    expect(offsetLabel("Asia/Kolkata")).toBe("UTC+5:30");
    expect(offsetLabel("America/Sao_Paulo")).toBe("UTC−3");
    expect(offsetLabel("Europe/Berlin", Date.parse("2026-07-01T12:00:00Z"))).toBe("UTC+2");
    expect(offsetLabel("Europe/Berlin", Date.parse("2026-12-01T12:00:00Z"))).toBe("UTC+1");
  });

  it("calls the installation's zone Local time and resolves it", () => {
    configureTimeZone({ plant: "America/Sao_Paulo", mode: "plant" });
    expect(timeZoneLabel(LOCAL_ZONE)).toBe("Local time · São Paulo (UTC−3)");
    expect(timeZoneLabel("")).toBe(timeZoneLabel(LOCAL_ZONE));
    expect(timeZoneLabel("Etc/GMT+5")).toBe("UTC−5");
    expect(timeZoneLabel("Etc/UTC")).toBe("UTC");
    expect(timeZoneLabel("America/New_York")).toMatch(/^New York \(UTC−[45]\)$/);
    expect(resolveTimeZone(LOCAL_ZONE)).toBe("America/Sao_Paulo");
    expect(resolveTimeZone("Not/AZone")).toBe("America/Sao_Paulo");
    expect(resolveTimeZone("Etc/GMT+3")).toBe("Etc/GMT+3");
    expect(cityName("America/Argentina/Buenos_Aires")).toBe("Argentina / Buenos Aires");
  });

  it("puts the person's default first, then the other, offsets, and cities last", () => {
    configureTimeZone({ plant: "America/Sao_Paulo", mode: "plant" });
    const groups = timeZoneGroups();
    expect(groups[0].options.map((option) => option.value)).toEqual([LOCAL_ZONE, "UTC"]);
    expect(groups[1].options.map((option) => option.label).slice(0, 3)).toEqual(["UTC−1", "UTC−2", "UTC−3"]);
    expect(groups[1].options).toHaveLength(26);
    expect(groups[2].options.some((option) => option.value === "America/Sao_Paulo")).toBe(true);
    expect(fixedOffsetZones().every(isFixedOffset)).toBe(true);
    configureTimeZone({ mode: "utc" });
    expect(timeZoneGroups()[0].options.map((option) => option.value)).toEqual(["UTC", LOCAL_ZONE]);
    expect(timeZoneGroups("Mars/Olympus")[0].options.map((option) => option.value)).toContain("Mars/Olympus");
    expect(timeZoneValue("")).toBe(LOCAL_ZONE);
    expect(timeZoneValue("Etc/UTC")).toBe("UTC");
  });

  it("shows UTC when the person chose it, and writes fixed offsets after the time", () => {
    configureTimeZone({ plant: "America/Sao_Paulo", mode: "utc" });
    expect(displayTimeZone()).toBe("UTC");
    expect(formatDate("2026-10-23T15:00:00Z")).toMatch(/3:00\sPM UTC$/);
    configureTimeZone({ plant: "Etc/GMT+3", mode: "plant" });
    expect(formatDate("2026-10-23T15:00:00Z")).toMatch(/12:00\sPM UTC−3$/);
  });

  it("writes the times of a file on the display zone's clock and names it in the header", () => {
    configureTimeZone({ plant: "America/Sao_Paulo", mode: "plant" });
    expect(fileTime("2026-10-23T15:00:00Z")).toBe("2026-10-23 12:00:00");
    expect(fileTime("label")).toBe("label");
    expect(fileTimeHeader()).toBe("time (UTC−3)");
    expect(fileStamp("2026-10-23T15:05:00Z")).toBe("202610231205");
    configureTimeZone({ mode: "utc" });
    expect(fileTimeHeader("at")).toBe("at (UTC)");
  });
});
