import { configureTimeZone } from "@plantcraft/ui";
import { describe, expect, it } from "vitest";
import { cardCsv, cardCsvName, defaultCard } from "./model";
import type { CardData } from "./types";

const base = { label: "FIC-1003 PV", signal: "plantcraft:FIC-1003.PV", unit: "m3/h", kind: "analog", error: null };

describe("card CSV export", () => {
  it("a trend is one row per sample, empty where there is no value", () => {
    const data: CardData = { card_id: "c1", kind: "trend", window: "1h", read_at: "2026-10-20T23:59:00Z",
      lines: [{ ...base, t: ["2026-10-20T23:00:00Z", "2026-10-20T23:01:00Z"], v: [12.5, null] }] };
    expect(cardCsv(data).split("\r\n")).toEqual([
      "time (UTC),label,signal,value,unit",
      "2026-10-20 23:00:00,FIC-1003 PV,plantcraft:FIC-1003.PV,12.5,m3/h",
      "2026-10-20 23:01:00,FIC-1003 PV,plantcraft:FIC-1003.PV,,m3/h",
      "",
    ]);
  });

  it("a table keeps its four aggregations, a KPI its value and state", () => {
    const row = { ...base, value: -3.25, at: "2026-10-20T23:00:00Z", agg: "mean", state: "warning" as const, values: { last: 1, mean: 2, min: 0, max: 4 } };
    const table = cardCsv({ card_id: "t", kind: "table", window: "8h", read_at: "x", rows: [row] }).split("\r\n");
    expect(table[0]).toBe("label,signal,last,mean,min,max,unit,at (UTC),state");
    expect(table[1]).toBe("FIC-1003 PV,plantcraft:FIC-1003.PV,1,2,0,4,m3/h,2026-10-20 23:00:00,warning");
    const kpi = cardCsv({ card_id: "k", kind: "stat", window: "8h", read_at: "x", rows: [row] }).split("\r\n");
    expect(kpi[1]).toBe("FIC-1003 PV,plantcraft:FIC-1003.PV,-3.25,m3/h,mean,2026-10-20 23:00:00,warning");
  });

  it("quotes separators and keeps text from being read as a formula", () => {
    const row = { ...base, label: 'Feed, "north"', value: "=HYPERLINK(1)", at: null, agg: "last", state: "none" as const, values: {} };
    const line = cardCsv({ card_id: "k", kind: "stat", window: "8h", read_at: "x", rows: [row] }).split("\r\n")[1];
    expect(line.startsWith('"Feed, ""north"""')).toBe(true);
    expect(line).toContain(",'=HYPERLINK(1),");
  });

  it("writes the times on the plant's clock and names its zone", () => {
    configureTimeZone({ plant: "America/Sao_Paulo", mode: "plant" });
    const data: CardData = { card_id: "c1", kind: "trend", window: "1h", read_at: "2026-10-20T23:59:00Z",
      lines: [{ ...base, t: ["2026-10-20T23:00:00Z"], v: [12.5] }] };
    expect(cardCsv(data).split("\r\n").slice(0, 2)).toEqual(["time (UTC−3),label,signal,value,unit", "2026-10-20 20:00:00,FIC-1003 PV,plantcraft:FIC-1003.PV,12.5,m3/h"]);
    expect(cardCsvName({ ...defaultCard("trend", []), title: "Feed" }, data)).toBe("feed-1h-202610202059.csv");
    configureTimeZone({ plant: null, mode: null });
  });

  it("names the file after the card, its window and when it was read", () => {
    const card = { ...defaultCard("trend", []), title: "Feed flow / North" };
    const data: CardData = { card_id: card.card_id, kind: "trend", window: "1h", read_at: "2026-10-20T23:59:12Z", lines: [] };
    expect(cardCsvName(card, data)).toBe("feed-flow-north-1h-202610202359.csv");
  });
});
