import { describe, expect, it } from "vitest";
import { NAV } from "./pages";

describe("the frame's pages", () => {
  it("the plant map holds the asset deep link; drawings and diagrams their pages", () => {
    const [map, drawings, diagrams] = NAV;
    expect(NAV.map((item) => item.to)).toEqual(["/", "/drawings", "/diagrams"]);
    for (const path of ["/", "/plant-map", "/assets/FIC-1001"]) expect(map.match?.(path)).toBe(true);
    expect(drawings.match?.("/drawings/abc")).toBe(true);
    expect(diagrams.match?.("/diagrams/abc/1")).toBe(true);
    expect(map.match?.("/help")).toBe(false);
  });
});
