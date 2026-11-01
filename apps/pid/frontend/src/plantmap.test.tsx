import { describe, expect, it } from "vitest";
import { compareTags } from "./PlantMapPage";
import type { PlantMap } from "./types";

const item = (tag: string, family = "equipment") => ({
  tag, family, cls: "pump", unit: "", area: "", sheet: "", confidence: "high" as const, why: "", places: [], in_plantcraft: null,
});

describe("compareTags", () => {
  it("reads the first cell of each line and splits the tags three ways", () => {
    const plant = { items: [item("P-1001"), item("FIC-1003", "instrument"), item("PID-U-1", "connector")] } as unknown as PlantMap;
    const result = compareTags('tag,description\n"p-1001",Feed pump\nE-1009;cooler\n\nnotes without a number\n', plant);
    expect(result.both).toEqual(["P-1001"]);
    expect(result.onlyDrawn).toEqual(["FIC-1003"]);
    expect(result.onlyList).toEqual(["E-1009"]);
  });
});
