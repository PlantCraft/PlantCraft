// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import { chosenFolder, configureFolders, FolderColumn, folderName, FolderPlaceLine, inFolder, LibraryColumn, newInFolder, NO_FOLDER, putInFolder, type FolderList } from "./Folders";
import { VersionLock, VersionsTab } from "./Versions";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve(); });

const LIST: FolderList = {
  folders: [{ folder_id: "f1", kind: "study", name: "Tuning", count: 1, created_by: "Ana", created_at: "2026-10-26T10:00:00Z" }],
  items: { a: { item_id: "a", folder_id: "f1", moved_by: "Bia", moved_at: "2026-10-26T11:00:00Z" } },
};

function setup() {
  const calls: Array<[string, RequestInit | undefined]> = [];
  configureFolders({
    request: async <T,>(path: string, init?: RequestInit) => { calls.push([path, init]); return (path.includes("/items/") ? { place: null } : LIST) as T; },
    href: (path) => `/models${path}`,
    listPath: (kind) => (kind === "study" ? "/studies" : `/${kind}s`),
  });
  return calls;
}

describe("folders", () => {
  it("reads ?folder= and filters a list by it", () => {
    expect(chosenFolder("?folder=f1")).toBe("f1");
    expect(chosenFolder("")).toBe("");
    expect(inFolder(LIST, "a", "")).toBe(true);
    expect(inFolder(LIST, "a", "f1")).toBe(true);
    expect(inFolder(LIST, "b", "f1")).toBe(false);
    expect(inFolder(LIST, "b", NO_FOLDER)).toBe(true);
    expect(inFolder(LIST, "a", NO_FOLDER)).toBe(false);
    expect(inFolder(null, "a", "f1")).toBe(false);
    expect(folderName(LIST, "f1")).toBe("Tuning");
    expect(folderName(LIST, NO_FOLDER)).toBe("In no folder");
    expect(newInFolder("/studies/new", "f1")).toBe("/studies/new?folder=f1");
    expect(newInFolder("/studies/new", NO_FOLDER)).toBe("/studies/new");
  });

  it("puts a new object in the chosen folder through the app's API", async () => {
    const calls = setup();
    await putInFolder("study", "s 1", NO_FOLDER);
    await putInFolder("study", "s 1", "f1");
    expect(calls).toHaveLength(1);
    expect(calls[0][0]).toBe("/api/folders/study/items/s%201");
    expect(JSON.parse(String(calls[0][1]?.body))).toEqual({ folder_id: "f1" });
  });

  it("shows the column with counts and the place line linking to the list", async () => {
    setup();
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    const chosen: string[] = [];
    act(() => root.render(createElement("div", null,
      createElement(FolderColumn, { kind: "study", list: LIST, chosen: "", onChoose: (value: string) => chosen.push(value), total: 3, canEdit: true, onChanged: () => undefined }),
      createElement(FolderPlaceLine, { kind: "study", itemId: "a", canEdit: false }))));
    await flush();
    const entries = [...host.querySelectorAll(".pc-folder")].map((item) => item.textContent);
    expect(entries).toEqual(["All3", "Tuning1", "In no folder2"]);
    expect(host.querySelector(".pc-folder-new")?.textContent).toBe("New folder");
    act(() => (host.querySelectorAll(".pc-folder")[1] as HTMLElement).click());
    expect(chosen).toEqual(["f1"]);
    const link = host.querySelector(".pc-folder-place a");
    expect(link?.getAttribute("href")).toBe("/models/studies?folder=f1");
    expect(host.querySelector(".pc-folder-place")?.textContent).toContain("moved by Bia");
    act(() => root.unmount());
  });

  it("shows libraries alone under their heading, with what goes under them (round 10)", () => {
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    const chosen: string[] = [];
    act(() => root.render(createElement(LibraryColumn, {
      libraries: [{ library: "dq", name: "Data quality", count: 4 }, { library: "mine", name: "Mine", count: 0 }],
      chosen: "dq", onChoose: (value: string) => chosen.push(value), footer: createElement("button", { className: "lib-new" }, "New library"),
    })));
    expect(host.querySelector(".pc-folder-heading")?.textContent).toBe("Libraries");
    expect([...host.querySelectorAll(".pc-folder")].map((item) => item.textContent)).toEqual(["Data quality4", "Mine0"]);
    expect(host.querySelector(".pc-folder-new")).toBeNull();
    expect(host.querySelector(".lib-new")?.textContent).toBe("New library");
    act(() => (host.querySelectorAll(".pc-folder")[1] as HTMLElement).click());
    expect(chosen).toEqual(["mine"]);
    act(() => root.unmount());
  });

  it("puts New version, or a lock, beside the versions' title", () => {
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    act(() => root.render(createElement(VersionsTab, { versions: [{ number: 1, current: true }], actions: createElement(VersionLock, null, "Ships with PlantCraft") })));
    expect(host.querySelector(".pc-versions .panel-header .pc-version-lock")?.textContent).toBe("Ships with PlantCraft");
    act(() => root.unmount());
  });
});
