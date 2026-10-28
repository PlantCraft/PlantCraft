import { describe, expect, it } from "vitest";
import { clampView, fullView, zoomAt, zoomLevel } from "./zoom";

describe("the viewer's zoom", () => {
  it("zooms about a point that stays put, inside the canvas", () => {
    const whole = fullView(4800, 2700);
    const closer = zoomAt(whole, 2, 1200, 675, 4800, 2700);
    expect(closer).toEqual({ x: 600, y: 337.5, w: 2400, h: 1350 });
    expect(zoomLevel(closer, 4800)).toBe(2);
    // The point under the pointer keeps its place: a quarter of the way across, before and after.
    expect((1200 - closer.x) / closer.w).toBeCloseTo((1200 - whole.x) / whole.w);
  });

  it("stops at the whole canvas and at an eighth of it", () => {
    expect(zoomAt(fullView(4800, 2700), 0.5, 0, 0, 4800, 2700)).toEqual(fullView(4800, 2700));
    expect(zoomAt(fullView(4800, 2700), 100, 4800, 2700, 4800, 2700)).toEqual({ x: 4200, y: 2362.5, w: 600, h: 337.5 });
  });

  it("keeps a moved view on the canvas", () => {
    expect(clampView({ x: -50, y: 3000, w: 1200, h: 675 }, 4800, 2700)).toEqual({ x: 0, y: 2025, w: 1200, h: 675 });
  });
});
