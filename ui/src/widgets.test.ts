import { describe, expect, it } from "vitest";
import { arrangeRows, cellClass, filterOptions, pageText, type DataColumn } from "./DataTable";
import { addToBoard, boardOf, defaultLayout, fetchAppWidgets, widgetDataUrl, fetchSuiteWidgets, listRows, moveWidget, nearestSize, placedItems, placedWidgets, sizeName, sizesOf, widgetSize, type WidgetDef } from "./Widgets";
import { freePlace, packCells, readingOrder } from "./Grid";
import { barCount, barScale, columnRects, factCount, seriesPaths, tileSide } from "./WidgetKinds";

type Row = { name: string; age: number | null };
const columns: DataColumn<Row>[] = [
  { key: "name", label: "Name", sort: (row) => row.name },
  { key: "age", label: "Age", sort: (row) => row.age },
];
const rows: Row[] = [{ name: "FIC-10", age: 4 }, { name: "FIC-2", age: null }, { name: "TIC-1", age: 14 }];

describe("DataTable", () => {
  it("sorts naturally, blanks last either way, and searches every word", () => {
    expect(arrangeRows(rows, columns, { key: "name", descending: false }, "", undefined).map((row) => row.name)).toEqual(["FIC-2", "FIC-10", "TIC-1"]);
    expect(arrangeRows(rows, columns, { key: "age", descending: true }, "", undefined).map((row) => row.name)).toEqual(["TIC-1", "FIC-10", "FIC-2"]);
    expect(arrangeRows(rows, columns, { key: "age", descending: false }, "", undefined).map((row) => row.name)).toEqual(["FIC-10", "TIC-1", "FIC-2"]);
    expect(arrangeRows(rows, columns, null, "fic 10", (row) => row.name).map((row) => row.name)).toEqual(["FIC-10"]);
  });

  it("filters a column by one of its values, before searching and sorting", () => {
    type Run = { id: string; kind: string; size: number };
    const runs: Run[] = [{ id: "a", kind: "backup", size: 3 }, { id: "b", kind: "update", size: 1 }, { id: "c", kind: "backup", size: 2 }];
    const by: DataColumn<Run>[] = [
      { key: "kind", label: "Kind", filter: true },
      { key: "size", label: "Size", sort: (row) => row.size, filter: { value: (row) => (row.size > 1 ? "big" : "small"), options: [{ value: "big", label: "Big" }, { value: "small", label: "Small" }] } },
    ];
    expect(filterOptions(runs, by[0])).toEqual([{ value: "backup", label: "backup", count: 2 }, { value: "update", label: "update", count: 1 }]);
    expect(filterOptions(runs, by[1]).map((item) => item.label)).toEqual(["Big", "Small"]);
    const kept = (filters: Record<string, string>) => arrangeRows(runs, by, { key: "size", descending: false }, "", undefined, filters).map((row) => row.id);
    expect(kept({ kind: ["backup"] })).toEqual(["c", "a"]);
    expect(kept({ kind: ["backup"], size: ["small"] })).toEqual([]);
    expect(kept({ kind: ["backup", "update"], size: ["small"] })).toEqual(["b"]);
    expect(kept({ kind: [] })).toEqual(["b", "c", "a"]);
  });

  it("says which rows the page shows", () => {
    expect(pageText(1, 25, 132)).toBe("26–50 of 132");
    expect(pageText(5, 25, 132)).toBe("126–132 of 132");
    expect(pageText(0, 25, 0)).toBe("0 of 0");
  });
});

describe("widgets", () => {
  const link = { id: "linkcraft", name: "PlantCraft Analytics", url: "/link/" };
  it("reads an app's catalog and ignores an app without one or of another version", async () => {
    const fetcher = (async (url: string) => {
      if (url === "/link/api/widgets") return new Response(JSON.stringify({ version: 1, widgets: [{ id: "worst", title: "Worst assets", size: "l", default: true, sizes: [{ w: 8, h: 3 }, { w: 4, h: 9 }, "x"] }, { id: "Bad Id", title: "x" }, { id: "plain", title: "Plain" }] }));
      if (url === "/twin/api/widgets") return new Response(JSON.stringify({ version: 2, widgets: [{ id: "a", title: "A" }] }));
      return new Response("", { status: 404 });
    }) as typeof fetch;
    expect(await fetchAppWidgets(link, fetcher)).toEqual([
      { id: "linkcraft:worst", app: "linkcraft", title: "Worst assets", description: undefined, size: "l", sizes: [{ w: 8, h: 3 }], dataUrl: "/link/api/widgets/worst", byDefault: true },
      { id: "linkcraft:plain", app: "linkcraft", title: "Plain", description: undefined, size: "m", dataUrl: "/link/api/widgets/plain", byDefault: false },
    ]);
    const all = await fetchSuiteWidgets([{ id: "processcraft", name: "PlantCraft", url: "/" }, link, { id: "twincraft", name: "Twin", url: "/twin/" }, { id: "dashcraft", name: "View", url: "/dash/" }], fetcher);
    expect(all.map((item) => item.id)).toEqual(["linkcraft:worst", "linkcraft:plain"]);
    expect(defaultLayout(all)).toEqual(["linkcraft:worst"]);
  });

  it("draws the saved layout with what is still installed, and moves within it", () => {
    const catalog: WidgetDef[] = [{ id: "a", app: "processcraft", title: "A", size: "s" }, { id: "b", app: "processcraft", title: "B", size: "m" }];
    expect(placedWidgets(["b", "gone", "a", "b"], catalog).map((item) => item.id)).toEqual(["b", "a"]);
    expect(moveWidget(["a", "b", "c"], "c", -1)).toEqual(["a", "c", "b"]);
    expect(moveWidget(["a", "b", "c"], "a", -1)).toEqual(["a", "b", "c"]);
  });

  it("places an older ordered list on the grid at each widget's size, and keeps placements", () => {
    const catalog: WidgetDef[] = [{ id: "a", app: "processcraft", title: "A", size: "s" }, { id: "b", app: "processcraft", title: "B", size: "m" }, { id: "c", app: "processcraft", title: "C", size: "l", h: 4 }];
    expect(widgetSize(catalog[0])).toEqual({ w: 3, h: 2 });
    const board = boardOf(["a", "b", "a", "c", "gone"], catalog);
    expect(board.map(({ i, x, y, w, h }) => [i, x, y, w, h])).toEqual([["a", 0, 0, 3, 2], ["b", 3, 0, 6, 3], ["c", 0, 3, 12, 3], ["gone", 0, 6, 6, 3]]);
    // A widget gone from the catalog stays saved but is not drawn.
    expect(placedItems(board, catalog).map((entry) => entry.item.i)).toEqual(["a", "b", "c"]);
    const saved = boardOf([{ i: "b", widget: "b", x: 6, y: 0, w: 6, h: 3, title: "Mine", config: { days: 7 } }, { widget: "a" }, { i: 3 }], catalog);
    expect(saved).toEqual([{ i: "b", widget: "b", x: 6, y: 0, w: 6, h: 3, title: "Mine", config: { days: 7 } }, { i: "a", widget: "a", x: 0, y: 0, w: 3, h: 2 }]);
    // A size saved before sizes were fixed becomes the closest one the widget allows.
    expect(boardOf([{ i: "c", widget: "c", x: 0, y: 0, w: 11, h: 7 }], catalog)[0]).toMatchObject({ w: 12, h: 3 });
  });

  it("gives each widget one to three fixed sizes, 1 to 3 rows high, and names them", () => {
    expect(sizesOf({ size: "s" })).toEqual([{ w: 3, h: 1 }, { w: 3, h: 2 }]);
    expect(sizesOf({ size: "m", sizes: [{ w: 6, h: 3 }, { w: 4, h: 2 }, { w: 6, h: 3 }, { w: 13, h: 1 }, { w: 4, h: 4 }] })).toEqual([{ w: 4, h: 2 }, { w: 6, h: 3 }]);
    expect(sizesOf({ size: "m", sizes: [{ w: 3, h: 1 }, { w: 4, h: 2 }, { w: 6, h: 2 }, { w: 12, h: 3 }] })).toHaveLength(3);
    expect(nearestSize({ size: "s" }, 6, 1)).toEqual({ w: 3, h: 1 });
    expect(widgetSize({ id: "x", app: "desk", title: "X", size: "m", sizes: [{ w: 4, h: 2 }, { w: 8, h: 3 }], w: 8, h: 3 })).toEqual({ w: 8, h: 3 });
    expect([0, 1].map((index) => sizeName(index, 2))).toEqual(["Small", "Large"]);
    expect([0, 1, 2].map((index) => sizeName(index, 3))).toEqual(["Small", "Medium", "Large"]);
    expect([1, 2, 3].map(listRows)).toEqual([1, 2, 4]);
  });

  it("adds a widget at the first free place, twice only when it may be placed more than once", () => {
    const list: WidgetDef = { id: "list", app: "desk", title: "List", size: "m", multiple: true, defaultConfig: { scope: "mine" } };
    const once = addToBoard([], list);
    expect(once).toEqual([{ i: "list", widget: "list", x: 0, y: 0, w: 6, h: 3, config: { scope: "mine" } }]);
    expect(addToBoard(once, list).map(({ i, x, y }) => [i, x, y])).toEqual([["list", 0, 0], ["list~2", 6, 0]]);
    expect(addToBoard([], list, { w: 4, h: 2 })[0]).toMatchObject({ w: 4, h: 2 });
  });

  it("packs cells row by row and reads them top to bottom, left to right", () => {
    expect(freePlace([{ i: "a", x: 0, y: 0, w: 12, h: 2 }], 4, 2)).toEqual({ x: 0, y: 2 });
    expect(packCells([{ i: "a", w: 8, h: 2 }, { i: "b", w: 6, h: 1 }, { i: "c", w: 4, h: 1 }]).map(({ i, x, y }) => [i, x, y])).toEqual([["a", 0, 0], ["b", 0, 2], ["c", 8, 0]]);
    expect(readingOrder([{ i: "b", x: 6, y: 0, w: 1, h: 1 }, { i: "c", x: 0, y: 3, w: 1, h: 1 }, { i: "a", x: 0, y: 0, w: 1, h: 1 }]).map((cell) => cell.i)).toEqual(["a", "b", "c"]);
  });
});

describe("Published widget shapes", () => {
  it("reads a widget about one picked thing, and asks for that thing's data", async () => {
    const fetcher = (async () => new Response(JSON.stringify({ version: 1, widgets: [{ id: "schedule", title: "Schedule", size: "m", pick: "Schedule" }] }), { status: 200 })) as typeof fetch;
    const [item] = await fetchAppWidgets({ id: "linkcraft", name: "Link", url: "/link/" }, fetcher);
    expect(item.pick).toBe("Schedule");
    expect(item.multiple).toBe(true);
    expect(typeof item.settings).toBe("function");
    expect(widgetDataUrl(item)).toBe("/link/api/widgets/schedule");
    expect(widgetDataUrl(item, { item: "s 1/a" })).toBe("/link/api/widgets/schedule?item=s%201%2Fa");
    // A widget without `pick` never sends one.
    expect(widgetDataUrl({ dataUrl: "/x/api/widgets/a" }, { item: "b" })).toBe("/x/api/widgets/a");
  });

  it("draws a series as a line with gaps, and needs two points", () => {
    expect(seriesPaths([[0, 1]])).toBeNull();
    const paths = seriesPaths([[0, 0], [1, 10], [2, null], [3, 5], [4, 5]]);
    expect(paths?.min).toBe(0);
    expect(paths?.max).toBe(10);
    // Two runs of the line: the gap breaks it.
    expect(paths?.line.match(/M/g)?.length).toBe(2);
    expect(seriesPaths([[0, 3], [1, 3]])?.line).toContain("M0.0,");
  });

  it("fits fewer facts in a smaller card", () => {
    expect(factCount(3, 1)).toBe(0);
    expect(factCount(4, 2)).toBe(2);
    expect(factCount(6, 2)).toBe(4);
    expect(factCount(6, 3)).toBe(8);
    expect(factCount(12, 2)).toBe(8);
  });
});

describe("bars, columns and tiles", () => {
  it("scales bars to the longest, the max or the target", () => {
    expect(barScale([{ label: "a", value: 4 }, { label: "b", value: 10 }])).toBe(10);
    expect(barScale([{ label: "a", value: 4 }], 20)).toBe(20);
    expect(barScale([{ label: "a", value: 4 }], null, 6)).toBe(6);
    expect(barScale([{ label: "a", value: null }, { label: "b", value: Number.NaN }])).toBe(1);
    expect([barCount(1), barCount(2), barCount(3), barCount(3, true)]).toEqual([1, 3, 5, 4]);
  });

  it("stacks each column, skips empty parts and draws the target at its height", () => {
    const chart = columnRects([[0, [2, 1]], [3_600_000, [0, null]], [7_200_000, [4, 0]]], 2, 8);
    expect(chart?.top).toBe(8);
    expect(chart?.rects.map((rect) => [rect.bucket, rect.stack])).toEqual([[0, 0], [0, 1], [2, 0]]);
    const [low, high] = chart!.rects;
    expect(high.y + high.h).toBeCloseTo(low.y);
    expect(chart?.targetY).toBeCloseTo(4);
    expect(columnRects([], 1)).toBeNull();
    expect(columnRects([[0, [0]]], 1)?.rects).toEqual([]);
  });

  it("shrinks the squares as there are more of them", () => {
    expect(tileSide(20, 3)).toBe(16);
    expect(tileSide(400, 3)).toBe(12);
    expect(tileSide(2000, 3)).toBe(7);
    expect(tileSide(400, 2)).toBe(9);
    expect(tileSide(200, 3)).toBe(16);
    expect(tileSide(200, 3, 6)).toBe(12);
  });
});

describe("table cells on a phone", () => {
  it("leave out the columns marked phone hide and keep numbers right-aligned", () => {
    expect(cellClass({ key: "a", label: "A" })).toBeUndefined();
    expect(cellClass({ key: "a", label: "A", numeric: true, className: "small" })).toBe("num small");
    expect(cellClass({ key: "a", label: "A", phone: "hide" })).toBe("pc-dt-phone-hide");
  });
});
