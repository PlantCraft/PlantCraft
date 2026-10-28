import { describe, expect, it } from "vitest";
import { fetchAppSearch, groupHits, isSearchKey, searchHref, searchItems, searchShortcut, SEARCH_FORMAT } from "./Search.js";
import type { SuiteApp } from "./SuiteShell.js";

const hist: SuiteApp = { id: "histcraft", name: "PlantCraft Historian", url: "/hist/" };
const platform: SuiteApp = { id: "processcraft", name: "PlantCraft", url: "/" };

function answer(status: number, body: unknown): typeof fetch {
  return (async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })) as typeof fetch;
}

describe("the suite's search", () => {
  it("joins an answer's path to its app's address and refuses links that leave it", () => {
    expect(searchHref(hist, "/points/FIC-101.PV")).toBe("/hist/points/FIC-101.PV");
    expect(searchHref(platform, "assets/FIC-101")).toBe("/assets/FIC-101");
    expect(searchHref({ ...hist, url: "/hist" }, "/points/x")).toBe("/hist/points/x");
    for (const bad of ["https://evil.example/", "//evil.example/x", "javascript:alert(1)", "/a/../../admin", "/a b", "/a\\b", ""]) expect(searchHref(hist, bad)).toBeNull();
  });

  it("keeps only answers of its format, cut to size", () => {
    const items = searchItems(hist, { format: SEARCH_FORMAT, items: [
      { title: "FIC-101.PV", detail: "Feed flow", type: "Point", href: "/points/FIC-101.PV" },
      { title: "", href: "/points/x" },
      { title: "Bad link", href: "https://evil.example/" },
      { title: "x".repeat(300), href: "/points/long" },
    ] });
    expect(items.map((item) => item.title.length)).toEqual([10, 120]);
    expect(items[0]).toMatchObject({ app: "histcraft", appName: "Historian", url: "/hist/points/FIC-101.PV", type: "Point" });
    expect(searchItems(hist, { format: "other/1", items: [{ title: "a", href: "/a" }] })).toEqual([]);
    expect(searchItems(hist, null)).toEqual([]);
  });

  it("adds nothing for an app that does not search or fails", async () => {
    expect(await fetchAppSearch(hist, "fic", { fetcher: answer(404, {}) })).toEqual([]);
    expect(await fetchAppSearch(hist, "fic", { fetcher: (async () => { throw new Error("down"); }) as typeof fetch })).toEqual([]);
    const found = await fetchAppSearch(hist, "fic 101", { fetcher: (async (url: string) => {
      expect(url).toBe("/hist/api/search?q=fic%20101&limit=6");
      return new Response(JSON.stringify({ format: SEARCH_FORMAT, items: [{ title: "FIC-101.PV", href: "/points/FIC-101.PV" }] }));
    }) as unknown as typeof fetch });
    expect(found).toHaveLength(1);
  });

  it("lists the answers by app in the apps' order", () => {
    const one = searchItems(hist, { format: SEARCH_FORMAT, items: [{ title: "a", href: "/a" }] });
    const two = searchItems(platform, { format: SEARCH_FORMAT, items: [{ title: "b", href: "/b" }] });
    expect(groupHits([platform, hist], { histcraft: one, processcraft: two }).map((group) => group.app)).toEqual(["processcraft", "histcraft"]);
    expect(groupHits([platform, hist], { histcraft: [] })).toEqual([]);
  });

  it("opens on Ctrl+K and Cmd+K only", () => {
    const key = (key: string, more: Partial<KeyboardEvent> = {}) => ({ key, ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, ...more });
    expect(isSearchKey(key("k", { ctrlKey: true }))).toBe(true);
    expect(isSearchKey(key("K", { metaKey: true }))).toBe(true);
    expect(isSearchKey(key("k"))).toBe(false);
    expect(isSearchKey(key("k", { ctrlKey: true, shiftKey: true }))).toBe(false);
    expect(searchShortcut("MacIntel")).toBe("⌘ K");
    expect(searchShortcut("Win32")).toBe("Ctrl K");
  });
});
