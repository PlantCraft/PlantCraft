import { describe, expect, it } from "vitest";
import { canNewVersion, chosenLibrary } from "./BlocksPage";

describe("round 10: blocks by library, PlantCraft's locked", () => {
  it("offers New version on a site block only, to whoever writes blocks", () => {
    expect(canNewVersion({ site: true, editable: true }, true)).toBe(true);
    expect(canNewVersion({ site: true, editable: true }, false)).toBe(false);
    // A block PlantCraft ships is locked, even where the server would take a version.
    expect(canNewVersion({ site: false, editable: true }, true)).toBe(false);
    expect(canNewVersion({ site: true, editable: true, locked: true }, true)).toBe(false);
  });

  it("opens on the library asked for, a site's one included", () => {
    const libraries = [{ library: "dq" }, { library: "smoothing" }];
    expect(chosenLibrary(libraries, "?library=smoothing")).toBe("smoothing");
    expect(chosenLibrary(libraries, "?library=gone")).toBe("dq");
  });
});
