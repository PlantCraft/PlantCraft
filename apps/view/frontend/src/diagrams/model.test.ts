import { describe, expect, it } from "vitest";
import { ARROWS, crosses, emptyDiagram, fitted, formatValue, labelSpot, lineDrawing, movedPage, onPage, pagesOf, placedOnPage, withoutPage, withPage, indexAt, levelBox, outlineOf, limitState, linePath, movableSegment, placeDir, resized, segmentMoved, placePoint, route, seriesTimes, shownAt, symbolBox, type Box, type DiagramData, type Element, type SymbolDef, type SymbolElement } from "./model";

const pump: SymbolDef = { id: "pump.p", title: "Pump", category: "pumps", w: 60, h: 40, svg: "<circle/>", ports: [{ id: "in", x: 0, y: 20, dir: "w" }, { id: "out", x: 60, y: 10, dir: "e" }], anchors: [], keywords: [] };
const at = (patch: Partial<SymbolElement> = {}): SymbolElement => ({ id: "p1", type: "symbol", symbol: "pump.p", x: 100, y: 100, w: 60, h: 40, rotate: 0, flip: false, label: "", label_position: "below", ...patch });

describe("diagram geometry", () => {
  it("places a port after scaling, flipping and turning the symbol", () => {
    expect(placePoint(at(), pump, 60, 10)).toEqual([160, 110]);
    expect(placePoint(at({ w: 120, h: 80 }), pump, 60, 10)).toEqual([220, 120]);
    expect(placePoint(at({ flip: true }), pump, 60, 10)).toEqual([100, 110]);
    // A quarter turn clockwise about the centre (130, 120): the right edge comes to the bottom.
    expect(placePoint(at({ rotate: 90 }), pump, 60, 20)).toEqual([130, 150]);
    expect(placeDir(at({ rotate: 90 }), "e")).toBe("s");
    expect(placeDir(at({ flip: true }), "e")).toBe("w");
  });

  it("routes a line between two ports with square bends", () => {
    const path = route([0, 0], "e", [100, 50], "w");
    expect(path[0]).toEqual([0, 0]);
    expect(path[path.length - 1]).toEqual([100, 50]);
    for (let index = 1; index < path.length; index += 1) {
      const [a, b] = [path[index - 1], path[index]];
      expect(a[0] === b[0] || a[1] === b[1]).toBe(true);
    }
    const tank = at({ id: "t1", x: 400 });
    const elements = new Map<string, Element>([["p1", at()], ["t1", tank]]);
    const line = linePath({ id: "l", type: "line", kind: "process", medium: "", points: [], start: { element: "p1", port: "out" }, end: { element: "t1", port: "nope" }, arrow: "end", label: "" }, elements, new Map([["pump.p", pump]]));
    expect(line[0]).toEqual([160, 110]);
    // An unknown port: the middle of the tank's side that faces the pump, entered square.
    expect(line[line.length - 1]).toEqual([400, 120]);
    expect(line[line.length - 2][1]).toBe(120);
  });

  it("resizes a symbol from a corner, the opposite one staying put", () => {
    // at() is 60 x 40 at (100, 100); dragging the south-east corner 60 right keeps the proportions.
    expect(resized(at(), "se", 60, 0, false, 0)).toMatchObject({ x: 100, y: 100, w: 120, h: 80 });
    expect(resized(at(), "se", 60, 0, true, 0)).toMatchObject({ w: 120, h: 40 });
    expect(resized(at(), "nw", 30, 20, true, 0)).toMatchObject({ x: 130, y: 120, w: 30, h: 20 });
    expect(resized(at(), "se", -500, -500, true, 0)).toMatchObject({ w: 16, h: 16 });
    // Turned a quarter, the box seen is 40 x 60; widening it grows the drawing's height.
    const turned = resized(at({ rotate: 90 }), "se", 40, 0, true, 0);
    expect(turned).toMatchObject({ w: 60, h: 80 });
  });

  it("moves the middle of a routed line across itself, keeping square bends", () => {
    const line = { id: "l", type: "line" as const, kind: "process" as const, medium: "", points: [], start: { element: "p1", port: "out" }, end: { element: "t1", port: "in" }, arrow: "end" as const, label: "" };
    const path = route([0, 0], "e", [100, 50], "w");
    const middle = path.findIndex((point, index) => index > 0 && point[0] === path[index + 1]?.[0] && point[1] !== path[index + 1]?.[1]);
    expect(movableSegment(line, path, 0)).toBe(false);
    expect(movableSegment(line, path, middle)).toBe(true);
    const points = segmentMoved(line, path, middle, 20, 10);
    const moved = [path[0], ...points, path[path.length - 1]];
    for (let index = 1; index < moved.length; index += 1) {
      const [a, c] = [moved[index - 1], moved[index]];
      expect(a[0] === c[0] || a[1] === c[1]).toBe(true);
    }
    expect(points.length).toBe(path.length - 2);
  });

  it("never squashes a drawing: one scale both ways, centred in its box", () => {
    // 60 x 40 in a 120 x 120 box: scale 2 (120 x 80), 20 above and below.
    const square = at({ w: 120, h: 120 });
    expect(fitted(square, pump)).toMatchObject({ x: 0, y: 20, w: 120, h: 80, sx: 2, sy: 2 });
    expect(placePoint(square, pump, 60, 10)).toEqual([220, 140]);
    expect(symbolBox(square, pump)).toEqual({ x: 100, y: 120, w: 120, h: 80 });
    expect(symbolBox(square)).toEqual({ x: 100, y: 100, w: 120, h: 120 });
    // A shape made to stretch fills any box.
    expect(placePoint(square, { ...pump, stretch: true }, 60, 10)).toEqual([220, 130]);
    // Turned a quarter, the drawn box is 80 wide and 120 high about the same centre.
    expect(symbolBox(at({ w: 120, h: 120, rotate: 90 }), pump)).toEqual({ x: 120, y: 100, w: 80, h: 120 });
  });

  it("resizes to the drawing's own proportions, from the box the drawing covers", () => {
    const squashed = at({ w: 60, h: 120 }); // drawn 60 x 40 in the middle (y 140..180)
    const grown = resized(squashed, "se", 60, 0, false, 10, 16, pump);
    expect(grown.w / grown.h).toBeCloseTo(1.5, 1);
    expect(grown).toMatchObject({ x: 100, y: 140, w: 120, h: 80 });
    expect(resized(squashed, "se", 60, 0, true, 10, 16, pump)).toMatchObject({ w: 120, h: 120 });
  });

  it("routes out of each port along its way, around the two symbols, on the grid", () => {
    const boxA: Box = { x: 200, y: 100, w: 60, h: 40 }, boxB: Box = { x: 40, y: 200, w: 60, h: 40 };
    // From A's east side to B's west side, B lying left of and below A: it must go round both.
    const path = route([260, 120], "e", [40, 220], "w", [boxA, boxB], 10);
    expect(path[0]).toEqual([260, 120]);
    expect(path[path.length - 1]).toEqual([40, 220]);
    expect(path[1][1]).toBe(120);
    expect(path[1][0]).toBeGreaterThanOrEqual(280); // a stub out east before the first bend
    expect(path[path.length - 2][1]).toBe(220);
    expect(path[path.length - 2][0]).toBeLessThanOrEqual(20); // and into B from the west
    for (let index = 1; index < path.length; index += 1) {
      const [a, b] = [path[index - 1], path[index]];
      expect(a[0] === b[0] || a[1] === b[1]).toBe(true);
      expect(crosses(a, b, boxA) || crosses(a, b, boxB)).toBe(false);
    }
    for (const corner of path.slice(1, -1)) expect(corner[0] % 10 === 0 || corner[1] % 10 === 0).toBe(true);
    expect(path.length).toBeLessThanOrEqual(7);
  });

  it("joins facing ports in line with one straight stretch, and an L with one bend", () => {
    expect(route([100, 50], "e", [300, 50], "w")).toEqual([[100, 50], [300, 50]]);
    expect(route([100, 50], "e", [300, 200], "n")).toEqual([[100, 50], [300, 50], [300, 200]]);
    // Into a port from below: the last stretch arrives going up.
    const up = route([100, 50], "e", [300, 200], "s");
    const [p, q] = [up[up.length - 2], up[up.length - 1]];
    expect(p[0]).toBe(q[0]);
    expect(p[1]).toBeGreaterThan(q[1]);
  });

  it("cuts a line to a symbol's centre where it meets the drawing's outline", () => {
    const tank = at({ id: "t1", x: 400, y: 100, w: 60, h: 40 });
    const elements = new Map<string, Element>([["p1", at()], ["t1", tank]]);
    const line = linePath({ id: "l", type: "line", kind: "signal", medium: "", points: [[300, 50], [430, 50]], start: { element: "p1", port: "" }, end: { element: "t1", port: "" }, arrow: "end", label: "" }, elements, new Map([["pump.p", pump]]));
    // From the pump's centre (130, 120) up its top edge to y 100; down onto the tank's top edge.
    expect(line[line.length - 1]).toEqual([430, 100]);
    expect(line[0][1]).toBeGreaterThanOrEqual(100);
  });

  it("draws small filled arrowheads on the ends and flow arrows on long runs", () => {
    const drawing = lineDrawing([[0, 0], [300, 0], [300, 100]], "process", "end");
    const [length] = ARROWS.process;
    expect(drawing.heads).toHaveLength(1);
    expect(drawing.heads[0][0]).toEqual([300, 100]);
    expect(drawing.heads[0][1][1]).toBeCloseTo(100 - length);
    // The stroke stops under the head, never past its tip.
    expect(drawing.stroke[2][1]).toBeLessThan(100);
    expect(drawing.stroke[2][1]).toBeGreaterThan(100 - length);
    expect(drawing.flows).toEqual([{ at: [150, 0], angle: 0 }]);
    expect(lineDrawing([[0, 0], [300, 0]], "signal", "none")).toMatchObject({ heads: [], flows: [] });
    expect(lineDrawing([[0, 0], [300, 0]], "process", "both").heads).toHaveLength(2);
  });

  it("puts a line's label over its longest level stretch", () => {
    expect(labelSpot([[0, 0], [40, 0], [40, 200], [300, 200]])).toEqual({ at: [170, 193], anchor: "middle" });
    expect(labelSpot([[0, 0], [0, 200]])).toEqual({ at: [7, 100], anchor: "start" });
  });

  it("finds the part that fills with the level", () => {
    expect(levelBox('<path d="M0 0"/><rect class="pc-level" x="4" y="16" width="72" height="96"/>')).toEqual({ x: 4, y: 16, w: 72, h: 96 });
    expect(levelBox("<rect/>")).toBeNull();
    expect(outlineOf('<path d="M1 1"/><path class="pc-state" d="M10,30 L50,20 Z" fill="none" stroke="currentColor" stroke-width="2"/>')).toBe('<path d="M10,30 L50,20 Z"/>');
    expect(outlineOf('<circle class="pc-state" cx="50" cy="50" r="40">')).toBe('<circle cx="50" cy="50" r="40"/>');
    expect(outlineOf("<rect/>")).toBeNull();
  });
});

describe("what a binding shows", () => {
  it("judges limits, numbers and instants", () => {
    expect(limitState({ high_warning: 80, high_alarm: 90 }, 85)).toBe("warning");
    expect(limitState({ low_alarm: 1 }, "AUTO")).toBe("unknown");
    expect(formatValue(1234.5)).toBe("1235");
    expect(formatValue(0.12345)).toBe("0.123");
    expect(formatValue(null)).toBe("—");
    expect(indexAt([10, 20, 30], 25)).toBe(1);
    expect(indexAt([10, 20, 30], 5)).toBe(-1);
  });

  it("shows the value now, or the last sample at the cursor", () => {
    const tank: SymbolElement = at({ id: "t1", level: { item: { signal_id: "s" }, min: 0, max: 200 } });
    const data: DiagramData = {
      read_at: "", range: { start: "2026-10-01T10:00:00Z", end: "2026-10-01T11:00:00Z", step: 60, live: true },
      bindings: [{ element: "t1", slot: "level", label: "Level", signal: "s", value: 150, state: "ok", fraction: 0.75 }],
      series: { s: { t: ["2026-10-01T10:00:00Z", "2026-10-01T10:30:00Z", "2026-10-01T10:31:00Z"], v: [20, 100, null] } },
    };
    const times = seriesTimes(data);
    expect(shownAt([tank], data, times, null).get("t1")?.level?.fraction).toBe(0.75);
    const later = shownAt([tank], data, times, Date.parse("2026-10-01T10:45:00Z")).get("t1")?.level;
    expect(later?.value).toBe(100);
    expect(later?.fraction).toBe(0.5);
    expect(shownAt([tank], data, times, Date.parse("2026-10-01T09:00:00Z")).get("t1")?.level?.state).toBe("unknown");
  });
});

describe("pages of a diagram", () => {
  const text = (id: string, page?: string): Element => ({ id, type: "text", x: 0, y: 0, text: id, size: 14, align: "start", bold: false, ...(page ? { page } : {}) });

  it("adds a page, giving a one-page diagram its first page, and draws each page alone", () => {
    const one = { ...emptyDiagram("Plant"), elements: [text("a")] };
    expect(pagesOf(one)).toEqual([{ id: "", name: "Plant" }]);
    const [two, added] = withPage(one, "Page 2");
    expect(pagesOf(two).map((page) => page.id)).toEqual(["p1", added]);
    expect(two.elements[0].page).toBe("p1");
    const drawn = { ...two, elements: [...two.elements, text("b", added)] };
    expect(onPage(drawn, added).elements.map((element) => element.id)).toEqual(["b"]);
    expect(onPage(drawn, "p1").elements.map((element) => element.id)).toEqual(["a"]);
    expect(movedPage(drawn, added, -1).pages?.map((page) => page.id)).toEqual([added, "p1"]);
  });

  it("removes a page with what is drawn on it and the links to it", () => {
    const [two, added] = withPage({ ...emptyDiagram(), elements: [{ ...text("go"), link: { kind: "page", target: "p2" } }] }, "Page 2");
    const drawn = { ...two, elements: [...two.elements, text("b", added)] };
    const left = withoutPage(drawn, added);
    expect(left.pages?.map((page) => page.id)).toEqual(["p1"]);
    expect(left.elements.map((element) => element.id)).toEqual(["go"]);
    expect(left.elements[0].link).toBeNull();
    expect(withoutPage(left, "p1")).toBe(left);
  });

  it("puts a drawing on a page, renaming ids another page uses and following its lines", () => {
    const kept = [text("tk1", "p1")];
    const drawing: Element[] = [
      { id: "tk1", type: "symbol", symbol: "vessel.tank", x: 0, y: 0, w: 40, h: 60, rotate: 0, flip: false, label: "", label_position: "below" },
      { id: "l1", type: "line", kind: "process", medium: "", points: [], start: { element: "tk1", port: "out" }, end: null, arrow: "end", label: "" },
    ];
    const placed = placedOnPage(drawing, kept, "p2");
    expect(placed.every((element) => element.page === "p2")).toBe(true);
    expect(placed[0].id).not.toBe("tk1");
    expect(placed[1].type === "line" && placed[1].start?.element).toBe(placed[0].id);
  });
});
