import { describe, expect, it } from "vitest";
import { NAV, tourSteps } from "./pages";
import { blockPath, blockTab, modelPath, modelTab, movedTo } from "./paths";

describe("the frame's pages", () => {
  it("one level, in Link's order: Overview, Blocks, Models, Studies, Executions", () => {
    const [overview, blocks, models, studies, executions] = NAV;
    expect(NAV.map((item) => item.to)).toEqual(["/", "/blocks", "/models", "/studies", "/executions"]);
    expect(NAV.some((item) => "children" in item)).toBe(false);
    expect(overview.match?.("/")).toBe(true);
    expect(overview.match?.("/models")).toBe(false);
    for (const path of ["/models", "/models/p-1/Pkg.Tank", "/models/p-1/Pkg.Tank/diagram", "/code/p-1", "/assets/FIC-101"]) expect(models.match?.(path)).toBe(true);
    for (const path of ["/studies", "/studies/st-1"]) expect(studies.match?.(path)).toBe(true);
    for (const path of ["/executions", "/executions/st-1", "/runs/r-1"]) expect(executions.match?.(path)).toBe(true);
    for (const path of ["/blocks", "/blocks/PlantCraftControl.PID"]) expect(blocks.match?.(path)).toBe(true);
    expect(models.match?.("/help")).toBe(false);
    expect(models.match?.("/modelsx")).toBe(false);
  });

  it("a model's and a block's tabs have addresses of their own", () => {
    expect(modelPath("p 1", "Pkg.Tank")).toBe("/models/p%201/Pkg.Tank");
    expect(modelPath("p-1", "Pkg.Tank", "inputs")).toBe("/models/p-1/Pkg.Tank/inputs");
    expect(["diagram", "test", "used-by", "settings", "nope", undefined].map(modelTab)).toEqual(["diagram", "test", "used-by", "settings", "overview", "overview"]);
    // The tabs of the round before keep their addresses.
    expect(["run", "studies"].map(modelTab)).toEqual(["test", "used-by"]);
    expect(blockPath("PlantCraftControl.PID", "used-by")).toBe("/blocks/PlantCraftControl.PID/used-by");
    expect(["code", "inputs", "x"].map(blockTab)).toEqual(["code", "inputs", "overview"]);
  });

  it("addresses of earlier versions lead to their new place", () => {
    expect(movedTo("/projects")).toBe("/models");
    expect(movedTo("/projects/p-1/studies")).toBe("/models");
    expect(movedTo("/projects/p-1/edit", "?model=A.B")).toBe("/code/p-1?model=A.B");
    expect(movedTo("/simulations/r-1")).toBe("/runs/r-1");
    expect(movedTo("/exports")).toBe("/executions");
    expect(movedTo("/models")).toBeNull();
  });

  it("the tour visits only pages of the app", () => {
    const paths = tourSteps().map((step) => step.path).filter(Boolean);
    for (const path of paths) expect(NAV.some((item) => item.match?.(path!))).toBe(true);
  });
});
