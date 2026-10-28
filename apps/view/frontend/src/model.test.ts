import { changeKind, rankSignals } from "./CardEditor";
import { describe, expect, it } from "vitest";
import { accessLabel, addPage, ALL_ROLES, exportDashboard, importDashboard, matchesSearch, cardPixels, cardsOn, CONTEXT, cardTitle, cellsOf, currentPage, draftOf, EMPTY_DRAFT, interpolate, minHeight, movePage, placeNew, removePage, defaultCard, formatValue, itemMode, itemName, maxItemsOf, readView, repeatCards, resultLabel, stateLabel, stateStatus, upgradeCard, usesContext, usesVariable, windowLabel, withCells, writeView } from "./model";
import type { Card } from "./types";

describe("cards", () => {
  it("default cards fit their kind and get unique ids", () => {
    const first = defaultCard("trend", []);
    const second = defaultCard("stat", [first]);
    expect(first.window).toBe("8h");
    expect(first.height).toBe(4);
    expect(defaultCard("stat", []).height).toBe(2);
    expect(second.width).toBe(3);
    expect(second.card_id).not.toBe(first.card_id);
  });
  it("a diagram card names a diagram, no signal, and is at least two rows high", () => {
    const card = defaultCard("diagram", []);
    expect(card.diagram_id).toBe("");
    expect(card.items).toEqual([]);
    expect(card.height).toBe(4);
    expect(minHeight("diagram")).toBe(2);
    expect(maxItemsOf("diagram")).toBe(0);
    expect(cardTitle(card)).toBe("Process display");
    const trend = { ...defaultCard("trend", []), items: [{ signal_id: "A" }] };
    const turned = changeKind(trend, "diagram");
    expect(turned.items).toEqual([]);
    expect(turned.diagram_id).toBe("");
    expect(changeKind({ ...turned, diagram_id: "d1" }, "diagram").diagram_id).toBe("d1");
  });
  it("titles say what the card shows", () => {
    const card = { ...defaultCard("stat", []), agg: "mean" as const, items: [{ asset_id: "fic-101", role: "pv" }] };
    expect(cardTitle(card)).toBe("fic-101 PV · mean");
    expect(cardTitle({ ...card, title: "Feed" })).toBe("Feed");
    const trend = { ...defaultCard("trend", []), items: [{ signal_id: "A" }, { signal_id: "B" }, { signal_id: "C" }] };
    expect(cardTitle(trend)).toBe("A and 2 more");
  });
  it("an item switched to Signal stays a signal item while its signal is picked", () => {
    expect(itemMode({ signal_id: "" })).toBe("signal");
    expect(itemMode({ signal_id: "plantcraft:FIC-1003.PV" })).toBe("signal");
    expect(itemMode({ asset_id: "fic-101", role: "pv" })).toBe("asset");
    expect(itemMode({ asset_id: CONTEXT, role: "pv", signal_id: null })).toBe("variable");
    expect(itemMode({ asset_id: "$loop", role: ALL_ROLES })).toBe("variable");
    expect(itemName({ asset_id: "$loop", role: ALL_ROLES })).toBe("${loop} signals");
    expect(cardTitle({ ...defaultCard("trend", []), items: [{ asset_id: "$loop", role: ALL_ROLES, roles: ["pv", "sp"] }] }, { loop: ["FIC-101"] })).toBe("FIC-101 PV, SP");
    expect(itemName({ asset_id: "fic-101", role: ALL_ROLES })).toBe("fic-101 signals");
  });

  it("knows when a dashboard needs an asset picker", () => {
    expect(usesContext([{ ...defaultCard("stat", []), items: [{ asset_id: CONTEXT, role: "pv" }] }])).toBe(true);
    expect(usesContext([{ ...defaultCard("stat", []), items: [{ signal_id: "A" }] }])).toBe(false);
  });
});

describe("formatting", () => {
  it("numbers, text and gaps", () => {
    expect(formatValue(49.8292)).toBe("49.8");
    expect(formatValue(49.97)).toBe("50.0");
    expect(formatValue(1234.5)).toBe("1,235");
    expect(formatValue(0.1234)).toBe("0.12");
    expect(formatValue(3, 2)).toBe("3.00");
    expect(formatValue("AUTO")).toBe("AUTO");
    expect(formatValue(null)).toBe("—");
  });
  it("windows and states", () => {
    expect(windowLabel("1h")).toBe("1 hour");
    expect(windowLabel("24h")).toBe("24 hours");
    expect(stateStatus("alarm")).toBe("critical");
    expect(stateStatus(undefined)).toBe("inactive");
  });
});

describe("view in the address", () => {
  it("round-trips and ignores junk", () => {
    const view = { vars: { loop: ["fic-101", "fic-102"], period: ["8h"] }, window: "8h", screen: true, edit: false, page: "p2" };
    expect(readView(writeView(view))).toEqual(view);
    expect(writeView(view)).toContain("var-loop=fic-101&var-loop=fic-102");
    expect(readView("?w=forever&asset=")).toEqual({ vars: {}, window: null, screen: false, edit: false, page: null });
    // The old asset picker's links still open the same asset.
    expect(readView("?asset=fic-101").vars).toEqual({ asset: ["fic-101"] });
  });
});

describe("app results", () => {
  it("read as people say them", () => {
    expect(resultLabel("linkcraft.loop_health")).toBe("Loop health (Analytics)");
    expect(resultLabel("cpmcraft.loop_health")).toBe("Loop health (Analytics)");
    expect(resultLabel("othertool.score")).toBe("Score (othertool)");
    expect(itemName({ asset_id: CONTEXT, result: "linkcraft.loop_health" })).toBe("Loop health (Analytics)");
    expect(stateLabel("unknown")).toBe("Unknown");
  });
});

describe("grid and pages", () => {
  it("rows keep the old short and tall cards' pixels", () => {
    expect(cardPixels(2)).toBe(196);
    expect(cardPixels(4)).toBe(406);
    expect(minHeight("trend")).toBe(2);
    expect(minHeight("stat")).toBe(1);
  });
  it("adds, moves and removes pages without moving cards", () => {
    const one = defaultCard("stat", []);
    const two = defaultCard("trend", [one]);
    const [draft, added] = addPage({ ...EMPTY_DRAFT, cards: [one, two] });
    expect(draft.pages.map((page) => page.page_id)).toEqual(["p1", added]);
    expect(draft.cards.every((card) => card.page_id === "p1")).toBe(true);
    const moved = movePage(draft, added, -1);
    expect(moved.pages[0].page_id).toBe(added);
    expect(cardsOn(moved, currentPage(moved.pages, null))).toEqual([]);
    expect(cardsOn(moved, currentPage(moved.pages, "p1")).length).toBe(2);
    const removed = removePage(moved, "p1");
    expect(removed.pages.map((page) => page.page_id)).toEqual([added]);
    expect(removed.cards).toEqual([]);
  });
  it("a dashboard without pages shows every card", () => {
    const card = defaultCard("stat", []);
    expect(currentPage([], "x")).toBeNull();
    expect(cardsOn({ pages: [], cards: [card] }, null)).toEqual([card]);
  });
});

describe("round 6: files, folders, search", () => {
  it("exports without the folder and imports a file or a bare dashboard", () => {
    const draft = { ...EMPTY_DRAFT, name: "Feed", folder_id: "f1", tags: ["Unit 100"] };
    const text = exportDashboard(draft);
    expect(JSON.parse(text).format).toBe("processcraft-dashboard");
    expect(importDashboard(text)).toEqual({ ...draft, folder_id: "" });
    expect(importDashboard(JSON.stringify({ name: "Bare", cards: [] })).name).toBe("Bare");
    expect(() => importDashboard("{\"name\": 3}")).toThrow();
  });
  it("says who a folder lets in", () => {
    expect(accessLabel([])).toBe("Everyone");
    expect(accessLabel(["group:ops"])).toBe("1 group");
    expect(accessLabel(["group:ops", "user:ana", "user:bo"])).toBe("1 group, 2 people");
  });
  it("finds dashboards by every word, in the name, description or tags", () => {
    const item = { name: "Feed section", description: "Unit 100", tags: ["valves"] };
    expect(matchesSearch(item, "feed valves")).toBe(true);
    expect(matchesSearch(item, "feed pumps")).toBe(false);
    expect(matchesSearch(item, "  ")).toBe(true);
  });
});

describe("signal search", () => {
  it("lists the numbers before the text signals, keeping the server's order otherwise", () => {
    const option = (id: string, kind: string) => ({ id, name: id, unit: "", description: "", kind });
    const ranked = rankSignals([option("FIC-1003.MODE", "text"), option("FIC-1003.OP", "number"), option("FIC-1003.PV", "number")]);
    expect(ranked.map((item) => item.id)).toEqual(["FIC-1003.OP", "FIC-1003.PV", "FIC-1003.MODE"]);
  });
});

describe("round 7: old cards, variables, the grid and repeats", () => {
  it("reads a card saved before round 7", () => {
    const old = { card_id: "a", title: "", kind: "kpi", items: [{ asset_id: CONTEXT, role: "pv" }], agg: "last", window: "1h", width: 3, height: 2,
      thresholds: { low_alarm: 10, low_warn: null, high_warn: 80, high_alarm: 90 }, decimals: 1, gauge_min: 0, gauge_max: 100 };
    const card = upgradeCard(old as unknown as Card & Record<string, unknown>);
    expect(card.kind).toBe("stat");
    expect(card.options.graph).toBe("none");
    expect(card.field.thresholds?.steps).toEqual([{ level: "alarm" }, { value: 10, level: "ok" }, { value: 80, level: "warning" }, { value: 90, level: "alarm" }]);
    expect(card.field).toMatchObject({ decimals: 1, min: 0, max: 100 });
    expect(card.items[0].asset_id).toBe("$asset");
    expect(upgradeCard({ ...old, kind: "spark" } as unknown as Card & Record<string, unknown>).options.graph).toBe("area");
  });
  it("turns the old asset picker into the variable asset", () => {
    const draft = draftOf({ name: "Loop", context_kind: "control_loop", cards: [] });
    expect(draft.variables).toEqual([{ name: "asset", label: "control_loop", type: "asset", asset_kind: "control_loop" }]);
  });
  it("fills variables in titles and finds where they are used", () => {
    expect(interpolate("Loop ${loop} over $period", { loop: ["FIC-101"], period: ["8 hours"] })).toBe("Loop FIC-101 over 8 hours");
    expect(interpolate("${unknown} stays", {})).toBe("${unknown} stays");
    const card = { ...defaultCard("trend", []), title: "${loop}", items: [{ asset_id: "$loop", role: ALL_ROLES }] };
    expect(cardTitle(card, { loop: ["FIC-101"] })).toBe("FIC-101");
    expect(usesVariable([card], "loop")).toBe(true);
    expect(usesVariable([card], "lo")).toBe(false);
    expect(usesContext([{ ...card, items: [{ asset_id: "$asset", role: "pv" }], title: "" }])).toBe(true);
  });
  it("places cards on the grid, keeps places, and puts new cards in the first free place", () => {
    const a = { ...defaultCard("trend", []), width: 8, height: 4, x: 0, y: 0 };
    const b = { ...defaultCard("stat", [a]), width: 4, height: 2 };
    const c = { ...defaultCard("stat", [a, b]), width: 4, height: 2 };
    const cells = cellsOf([a, b, c]);
    expect(cells.map(({ x, y }) => [x, y])).toEqual([[0, 0], [8, 0], [8, 2]]);
    const moved = withCells([a, b, c], [{ ...cells[0], x: 4 }, { ...cells[1], x: 0, w: 3, h: 1 }, cells[2]]);
    expect(moved[0].x).toBe(4);
    expect([moved[1].width, moved[1].height]).toEqual([3, 1]);
    // A trend never gets shorter than two rows, whatever the grid says.
    expect(withCells([a], [{ ...cells[0], h: 1 }])[0].height).toBe(2);
    const placed = placeNew({ ...defaultCard("stat", []), width: 4, height: 2 }, [a, { ...b, x: 8, y: 0 }]);
    expect([placed.x, placed.y]).toEqual([8, 2]);
  });
  it("repeats a card for each value, side by side, and moves the cards under it down", () => {
    const loop = { ...defaultCard("stat", []), width: 4, height: 2, x: 0, y: 0, repeat: { variable: "loop", direction: "h" as const, max_per_row: 2 } };
    const under = { ...defaultCard("trend", [loop]), width: 12, height: 4, x: 0, y: 2 };
    const { shown, cells } = repeatCards([loop, under], { loop: ["a", "b", "c"] }, { loop: ["A", "B", "C"] });
    expect(shown.map((item) => item.values.loop)).toEqual([["a"], ["b"], ["c"], ["a", "b", "c"]]);
    expect(shown[1].texts.loop).toEqual(["B"]);
    const byId = Object.fromEntries(cells.map((cell) => [cell.i, cell]));
    expect([byId[loop.card_id].w, byId[`${loop.card_id}~1`].x, byId[`${loop.card_id}~2`].y]).toEqual([6, 6, 2]);
    expect(byId[under.card_id].y).toBe(4);
    // One value: the card as it is.
    expect(repeatCards([loop], { loop: ["a"] }, {}).shown).toHaveLength(1);
  });
  it("repeats one under the other keeping the card's width", () => {
    const loop = { ...defaultCard("stat", []), width: 4, height: 2, x: 2, y: 0, repeat: { variable: "loop", direction: "v" as const, max_per_row: 4 } };
    const { cells } = repeatCards([loop], { loop: ["a", "b"] }, {});
    expect(cells.map(({ x, y, w }) => [x, y, w])).toEqual([[2, 0, 4], [2, 2, 4]]);
  });
});
