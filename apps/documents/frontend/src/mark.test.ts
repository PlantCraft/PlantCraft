import { describe, expect, it } from "vitest";
import { searchWords, snippetOf, wordRanges } from "./mark";

describe("the words of a search marked in a passage", () => {
  it("keeps the words worth marking and the tags, folded", () => {
    expect(searchWords("Why does the válvula FIC1003 cycle?")).toEqual(["fic1003", "valvula", "cycle"]);
  });
  it("finds a tag with or without its dash, and accented words", () => {
    const text = "FIC-1003 cycles: the válvula sticks.";
    expect(wordRanges(text, ["fic1003", "valvula"]).map(([a, b]) => text.slice(a, b))).toEqual(["FIC-1003", "válvula"]);
  });
  it("cuts a long passage around the first word found", () => {
    const text = `${"filler ".repeat(200)}the separator pressure oscillates ${"tail ".repeat(200)}`;
    const cut = snippetOf(text, ["separator"], 200);
    expect(cut.text.startsWith("…")).toBe(true);
    expect(cut.text).toContain("separator pressure");
    expect(cut.text.length).toBeLessThanOrEqual(202);
  });
});
