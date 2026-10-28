import { describe, expect, it } from "vitest";
import { suiteName } from "./AppsPage";

describe("installed apps", () => {
  it("names a suite app as the suite does today, whatever its manifest says", () => {
    expect(suiteName({ id: "linkcraft", name: "PlantCraft Analytics" })).toBe("PlantCraft Analytics");
    expect(suiteName({ id: "dashcraft", name: "PlantCraft View" })).toBe("PlantCraft View");
    expect(suiteName({ id: "acme-lims", name: "ACME LIMS" })).toBe("ACME LIMS");
  });
});
