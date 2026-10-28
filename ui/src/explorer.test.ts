import { describe, expect, it } from "vitest";
import { outputsByApp, pathWords, pickOfHit, wanted, type ExploreHit } from "./Explorer.js";

const path = [{ id: "u1", name: "Unit 100" }, { id: "fic", name: "FIC-1001" }];

describe("the Explorer", () => {
  it("picks a value with the asset it was found on, for \"this asset\" in a rule over many", () => {
    const hit: ExploreHit = { type: "output", id: "app-linkcraft:fic.valve.health", name: "Valve health", unit: "/100", app: "linkcraft", app_name: "Link", path };
    expect(pickOfHit(hit)).toMatchObject({ type: "output", id: hit.id, relativeTo: "fic", app: "linkcraft", unit: "/100" });
    expect(pickOfHit({ type: "asset", id: "fic", name: "FIC-1001", path: path.slice(0, 1) }).relativeTo).toBeNull();
    expect(pickOfHit({ type: "signal", id: "s:x", name: "x", path: [] }).relativeTo).toBeNull();
  });

  it("offers only what the caller wants", () => {
    expect(wanted(["value"], "signal") && wanted(["value"], "output")).toBe(true);
    expect(wanted(["value"], "event") || wanted(["value"], "asset")).toBe(false);
    expect(wanted(["event", "asset"], "event") && wanted(["event", "asset"], "asset")).toBe(true);
  });

  it("names a path and groups the outputs by the app that computed them", () => {
    expect(pathWords(path)).toBe("Unit 100 › FIC-1001");
    expect(pathWords([])).toBe("");
    const groups = outputsByApp([
      { id: "a", name: "Health", unit: "/100", app: "linkcraft", app_name: "Link" },
      { id: "b", name: "Fit", unit: "", app: "modelcraft", app_name: "Models" },
      { id: "c", name: "Stiction", unit: "", app: "linkcraft", app_name: "Link" },
    ]);
    expect(groups.map((group) => [group.name, group.outputs.map((item) => item.id)])).toEqual([["Link", ["a", "c"]], ["Models", ["b"]]]);
  });
});
