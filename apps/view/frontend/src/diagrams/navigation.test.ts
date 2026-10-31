import { describe, expect, it } from "vitest";
import { backOf, backQuery, openOf } from "./DiagramPage";
import type { Element } from "./model";

describe("moving between process displays (V9)", () => {
  const linked = { id: "b1", type: "symbol", symbol: "shape.panel", x: 0, y: 0, w: 10, h: 10, link: { kind: "diagram", target: "unit-2" } } as unknown as Element;

  it("a link to another display carries the way back, with the page it was on", () => {
    expect(openOf(linked, null, { id: "plant", page: "p2" })).toEqual({ kind: "go", to: "/diagrams/unit-2?from=plant&from_page=p2" });
    expect(openOf(linked, null, { id: "plant" })).toEqual({ kind: "go", to: "/diagrams/unit-2?from=plant" });
    expect(openOf(linked, null)).toEqual({ kind: "go", to: "/diagrams/unit-2" });
  });

  it("Back leads to the display and the page it came from", () => {
    expect(backOf("?from=plant&from_page=p2")).toEqual({ id: "plant", to: "/diagrams/plant?page=p2" });
    expect(backOf("?from=a%2Fb")).toEqual({ id: "a/b", to: "/diagrams/a%2Fb" });
    expect(backOf("?page=p1")).toBeNull();
    expect(backQuery()).toBe("");
  });
});
