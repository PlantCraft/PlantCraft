import { describe, expect, it } from "vitest";
import { ALL_LEVELS, openToLevel } from "./assetTree";

const node = (asset_id: string) => ({ asset_id });
// plant > u1 > a1 > p1, plant > u2 (no children)
const tree = new Map<string | null, { asset_id: string }[]>([
  [null, [node("plant")]],
  ["plant", [node("u1"), node("u2")]],
  ["u1", [node("a1")]],
  ["a1", [node("p1")]],
]);

describe("openToLevel", () => {
  it("level 1 opens only the installation: its units show", () => {
    expect([...openToLevel(tree, 1)]).toEqual(["plant"]);
  });
  it("level 2 also opens the units that hold something", () => {
    expect([...openToLevel(tree, 2)].sort()).toEqual(["plant", "u1"]);
  });
  it("all levels opens every folder and never a leaf", () => {
    expect([...openToLevel(tree, ALL_LEVELS)].sort()).toEqual(["a1", "plant", "u1"]);
  });
  it("level 0 closes everything", () => {
    expect(openToLevel(tree, 0).size).toBe(0);
  });
});
