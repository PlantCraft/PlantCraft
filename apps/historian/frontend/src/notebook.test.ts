import { describe, expect, it } from "vitest";
import { notebookHref } from "./notebook";

describe("open in a notebook", () => {
  it("names the signals, the period and the step", () => {
    const href = notebookHref("/notebooks", ["plant:FIC-101.PV", "plant:FIC-101.SP"], "-24h", "now", 600);
    const params = new URLSearchParams(href.slice(href.indexOf("?")));
    expect(href.startsWith("/notebooks?")).toBe(true);
    expect(params.get("signals")).toBe("plant:FIC-101.PV,plant:FIC-101.SP");
    expect([params.get("start"), params.get("end"), params.get("step"), params.get("origin")]).toEqual(["-24h", "now", "600", "the Historian"]);
    expect(new URLSearchParams(notebookHref("/notebooks", ["a:b"], "x", "y").split("?")[1]).has("step")).toBe(false);
  });
});
