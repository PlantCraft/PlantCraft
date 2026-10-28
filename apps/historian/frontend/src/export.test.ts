import { describe, expect, it } from "vitest";
import { addTags, assetPaths, kindOptions, matchAssets, TAG_KIND } from "./ExportPage";
import type { ExportTag } from "./api";
import type { ExportAsset } from "./types";

const asset = (id: string, name: string, parent_id: string | null, kind = "unit"): ExportAsset => ({ id, name, kind, kind_label: kind === "loop" ? "Control loop" : "Unit", parent_id, depth: 0, loop: kind === "loop", loops: 0, signals: 1, missing: 0 });
const TREE = [asset("site", "Site", null), asset("u100", "Unit 100", "site"), asset("fic-101", "FIC-101", "u100", "loop"), asset("u200", "Unit 200", "site")];
const tag = (signal: string): ExportTag => ({ signal, tag: signal, name: "", unit: "", archived: true });

describe("export choices", () => {
  it("names each asset by the path above it", () => {
    expect(assetPaths(TREE)).toEqual({ site: "", u100: "Site", "fic-101": "Site / Unit 100", u200: "Site" });
  });

  it("finds assets by name, id or path, of the kinds chosen", () => {
    const paths = assetPaths(TREE);
    expect(matchAssets(TREE, paths, "unit 100").map((item) => item.id)).toEqual(["u100", "fic-101"]);
    expect(matchAssets(TREE, paths, "fic").map((item) => item.id)).toEqual(["fic-101"]);
    expect(matchAssets(TREE, paths, " ")).toHaveLength(4);
    expect(matchAssets(TREE, paths, "", ["loop"]).map((item) => item.id)).toEqual(["fic-101"]);
    expect(matchAssets(TREE, paths, "unit", [TAG_KIND])).toEqual([]);
  });

  it("filters by tags and by every kind of asset, a loop being one of them", () => {
    expect(kindOptions(TREE, 42).map((item) => [item.id, item.count])).toEqual([[TAG_KIND, 42], ["loop", 1], ["unit", 3]]);
  });

  it("adds each tag to the list once, in order", () => {
    expect(addTags([tag("a"), tag("b")], [tag("b"), tag("c"), tag("c")]).map((item) => item.signal)).toEqual(["a", "b", "c"]);
  });
});
