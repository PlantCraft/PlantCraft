import { describe, expect, it } from "vitest";
import { ATTACHMENT_PREFIX, leaveAttachment, parseResult, resultActionUrl, resultRef, resultText } from "./loopResult";
import type { LoopDetail, Me } from "./types";

const detail = {
  loop: { loop_id: "FIC-101", name: "Feed flow", metadata: { asset_id: "asset-7" } },
  origin: "processcraft",
  summary: { status: "high", health: 42, limiting: { method_id: "stiction_screening", finding: "Valve sticks" } },
  likely_causes: [{ cause_id: "stiction", cause: "Valve stiction", strength: 3, evidence: [], action: "Check the valve in the field." }],
  results: [],
  source_start: "2026-10-31T06:00:00Z",
  source_end: "2026-10-31T12:00:00Z",
} as unknown as LoopDetail;

describe("a verdict as an action", () => {
  it("names the loop and the window, and reads back", () => {
    expect(resultRef("FIC-101", "2026-10-31T12:00:00Z")).toBe("loop_result:FIC-101@2026-10-31T12:00:00Z");
    expect(parseResult("FIC-101@2026-10-31T12:00:00Z")).toEqual({ loopId: "FIC-101", end: "2026-10-31T12:00:00Z" });
    expect(parseResult("me@plant")).toEqual({ loopId: "me@plant", end: null });
  });

  it("opens PlantCraft's form with the verdict, its references and the image key", () => {
    const url = new URL(resultActionUrl({ processcraft_url: "/" } as Me, detail, "k1"), "https://suite.local");
    expect(url.pathname).toBe("/actions");
    expect(url.searchParams.getAll("ref")).toEqual(["asset:asset-7", "loop_result:FIC-101@2026-10-31T12:00:00Z"]);
    expect(url.searchParams.get("attach")).toBe("k1");
    const text = url.searchParams.get("text") ?? "";
    expect(text).toContain("health 42");
    expect(text).toContain("Valve stiction");
    expect(text.endsWith("#loop_result:FIC-101@2026-10-31T12:00:00Z")).toBe(true);
    // A loop defined in Analytics has no PlantCraft asset: only the verdict.
    const own = new URL(resultActionUrl({ processcraft_url: "/" } as Me, { ...detail, origin: "linkcraft" } as LoopDetail, null), "https://suite.local");
    expect(own.searchParams.getAll("ref")).toEqual(["loop_result:FIC-101@2026-10-31T12:00:00Z"]);
    expect(own.searchParams.has("attach")).toBe(false);
    expect(resultText(detail, "loop_result:x").length).toBeLessThanOrEqual(4000);
  });

  it("leaves the image where PlantCraft's form reads it", () => {
    const items: Record<string, string> = {};
    const key = leaveAttachment("FIC-101.png", "data:image/png;base64,AAAA", { setItem: (name, value) => { items[name] = value; } });
    expect(key).toMatch(/^[a-z0-9]+$/);
    expect(JSON.parse(items[ATTACHMENT_PREFIX + key])).toEqual({ name: "FIC-101.png", data: "data:image/png;base64,AAAA" });
  });
});
