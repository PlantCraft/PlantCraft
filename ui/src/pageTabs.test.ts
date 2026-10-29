import { describe, expect, it } from "vitest";
import { moreSides } from "./PageTabs.js";

describe("page tabs on a narrow screen", () => {
  it("fades only the edges with more tabs past them", () => {
    expect(moreSides(0, 390, 390)).toEqual({ left: false, right: false });
    expect(moreSides(0, 390, 700)).toEqual({ left: false, right: true });
    expect(moreSides(150, 390, 700)).toEqual({ left: true, right: true });
    expect(moreSides(310, 390, 700)).toEqual({ left: true, right: false });
  });
});
