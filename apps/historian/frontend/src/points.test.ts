import { describe, expect, it } from "vitest";
import { formulaInputs } from "./CalcPoint";
import type { Point } from "./types";
import { plantFirst, statusLabel } from "./PointsPage";

describe("point list order", () => {
  it("lists the plant's points before the series apps write", () => {
    const rows = [
      { source_id: "app-linkcraft", signal: "app-linkcraft:AIC-1006.health" },
      { source_id: "plantcraft", signal: "plantcraft:CPM.Loops.FIC-1003.PV" },
      { source_id: "plantcraft", signal: "plantcraft:CPM.Loops.AIC-1006.PV" },
    ];
    expect([...rows].sort(plantFirst).map((row) => row.signal)).toEqual([
      "plantcraft:CPM.Loops.AIC-1006.PV",
      "plantcraft:CPM.Loops.FIC-1003.PV",
      "app-linkcraft:AIC-1006.health",
    ]);
  });
});

describe("formulaInputs", () => {
  it("offers only numbers the collector archives", () => {
    const point = (signal: string, source_kind: string, mode: string, kind = "number") => ({ signal, source_kind, mode, kind }) as unknown as Point;
    const rows = [
      point("plant:F", "opcua", "archive"),
      point("plant:G", "opcua", "both"),
      point("plant:H", "opcua", "source"),
      point("plant:MODE", "opcua", "archive", "text"),
      point("pi:F", "pi_web_api", "source"),
      point("calc:X", "calc", "archive"),
      point("app-linkcraft:h", "derived", "archive"),
    ];
    expect(formulaInputs(rows).map((row) => row.signal)).toEqual(["plant:F", "plant:G", "calc:X"]);
  });
});

describe("statusLabel", () => {
  it("says an imported or app-written point is not collecting", () => {
    expect(statusLabel({ status: "ok", source_kind: "import" })).toBe("Imported");
    expect(statusLabel({ status: "ok", source_kind: "derived" })).toBe("Written by its app");
    expect(statusLabel({ status: "ok", source_kind: "opcua" })).toBe("Collecting");
    expect(statusLabel({ status: "bad", source_kind: "import" })).toBe("Bad value");
  });
});
