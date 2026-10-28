// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

describe("widget hover notes", () => {
  it("finds the point nearest the pointer by time, over gaps", async () => {
    const { nearestPoint } = await import("./WidgetKinds");
    const points: Array<[number, number | null]> = [[0, 1], [10, null], [20, 3], [30, 4]];
    expect(nearestPoint(points, 0)).toBe(0);
    expect(nearestPoint(points, 0.3)).toBe(0); // 10 is a gap: 0 is nearer than 20
    expect(nearestPoint(points, 0.7)).toBe(2);
    expect(nearestPoint(points, 1)).toBe(3);
    expect(nearestPoint([[0, null]], 0.5)).toBeNull();
  });

  it("writes a mark's note as text, never as markup", async () => {
    const { fillTip } = await import("./WidgetTip");
    const target = document.createElement("div");
    fillTip(target, { title: "FIC-101.PV", group: "plantcraft", color: "red", rows: [["", "Collecting"], ["Values", "<b>12</b>"]] });
    expect(target.querySelector(".pc-wg-tip-head b")?.textContent).toBe("FIC-101.PV");
    expect(target.querySelector("small")?.textContent).toBe("plantcraft");
    expect(Array.from(target.querySelectorAll(".pc-wg-tip-row")).map((row) => row.textContent)).toEqual(["Collecting", "Values<b>12</b>"]);
    expect(target.querySelectorAll(".pc-wg-tip-row b b")).toHaveLength(0);
  });
});
