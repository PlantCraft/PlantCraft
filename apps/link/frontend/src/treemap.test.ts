import { describe, expect, it } from "vitest";
import { squarify } from "./treemap";

describe("squarify", () => {
  it("fills the box with areas in proportion to the weights", () => {
    const placed = squarify([6, 6, 4, 3, 2, 2, 1], (n) => n, { x: 0, y: 0, w: 6, h: 4 });
    expect(placed).toHaveLength(7);
    const total = placed.reduce((sum, rect) => sum + rect.w * rect.h, 0);
    expect(total).toBeCloseTo(24, 6);
    for (const rect of placed) {
      expect(rect.w * rect.h).toBeCloseTo(rect.item, 6);
      expect(rect.x).toBeGreaterThanOrEqual(-1e-9);
      expect(rect.y).toBeGreaterThanOrEqual(-1e-9);
      expect(rect.x + rect.w).toBeLessThanOrEqual(6 + 1e-9);
      expect(rect.y + rect.h).toBeLessThanOrEqual(4 + 1e-9);
    }
  });

  it("skips empty weights and an empty box", () => {
    expect(squarify([0, -1, Number.NaN], (n) => n, { x: 0, y: 0, w: 1, h: 1 })).toEqual([]);
    expect(squarify([1], (n) => n, { x: 0, y: 0, w: 0, h: 1 })).toEqual([]);
  });
});
