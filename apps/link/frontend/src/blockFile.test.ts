import { describe, expect, it } from "vitest";
import { lineDiff } from "@plantcraft/ui";
import { contractChanged, fileName, newBlockFile, parseBlockFile } from "./blockFile";
import { blockRoute, madeBy } from "./BlocksPage";

describe("block files", () => {
  it("reads a file wrapped in an assistant's fenced answer", () => {
    const file = { ...newBlockFile(), name: "UA drift" };
    const parsed = parseBlockFile(`Here it is:\n\`\`\`json\n${JSON.stringify(file)}\n\`\`\`\nUse it well.`);
    expect(parsed.name).toBe("UA drift");
    expect(parsed.code).toContain("def run(");
  });

  it("refuses text that is not a JSON object", () => {
    expect(() => parseBlockFile("[1, 2]")).toThrow(/JSON object/);
    expect(() => parseBlockFile("no json here")).toThrow(/Not a block file/);
  });

  it("names the file by its pinned id", () => {
    expect(fileName({ ...newBlockFile(), name: "UA drift" })).toBe("custom.ua_drift.json");
    expect(fileName({ ...newBlockFile(), block_id: "custom.ua_drift", version: { number: 3 } } as never)).toBe("custom.ua_drift.v3.json");
  });

  it("diffs code line by line", () => {
    const kinds = lineDiff("a\nb\nc", "a\nc\nd").map((line) => `${line.kind}:${line.text}`);
    expect(kinds).toEqual(["same:a", "removed:b", "same:c", "added:d"]);
  });

  it("sees a change of ports, not of text", () => {
    const before = newBlockFile();
    expect(contractChanged(before, { ...before, code: "x" })).toBe(false);
    expect(contractChanged(before, { ...before, outputs: [{ ...before.outputs[0], type: "number" }] })).toBe(true);
  });
});

describe("block pages", () => {
  it("splits a route into the block and its tab", () => {
    expect(blockRoute("custom.ua_drift")).toEqual({ blockId: "custom.ua_drift", tab: "overview" });
    expect(blockRoute("custom.ua_drift/code")).toEqual({ blockId: "custom.ua_drift", tab: "code" });
    expect(blockRoute("custom.ua_drift/edit")).toEqual({ blockId: "custom.ua_drift", tab: "edit" });
    expect(blockRoute("custom.ua_drift/parameters")).toEqual({ blockId: "custom.ua_drift", tab: "inputs" });
    expect(blockRoute("custom.ua_drift/used-by")).toEqual({ blockId: "custom.ua_drift", tab: "used-by" });
  });

  it("says who made a block", () => {
    expect(madeBy({ site: false, author_name: "", number: null })).toBe("PlantCraft");
    expect(madeBy({ site: true, author_name: "Ana", number: 2 })).toBe("Ana · version 2");
  });
});

describe("a block the assistant proposed", () => {
  it("fills in the form from the card's fields", async () => {
    const { blockFromDraft } = await import("./blockFile");
    const file = blockFromDraft({ name: "UA drift", summary: "How far UA moved from its baseline.", inputs: ["Hot inlet T: the hot side's inlet", "flow"],
      outputs: ["drift: percent change"], parameters: ["window = 30: samples per average", "mode = fast"], code: "def run(inputs, params, ctx):\n    return {}\n" });
    expect(file.origin).toBe("assistant");
    expect(file.inputs.map((port) => [port.port, port.label, port.description])).toEqual([["hot_inlet_t", "Hot inlet T", "the hot side's inlet"], ["flow", "flow", ""]]);
    expect(file.outputs[0]).toMatchObject({ port: "drift", description: "percent change" });
    expect(file.parameters).toMatchObject([{ name: "window", type: "integer", default: 30 }, { name: "mode", type: "text", default: "fast" }]);
    expect(file.code).toContain("return {}");
    expect(blockFromDraft({ name: "x" }).code).toContain("def run(");
  });
});
