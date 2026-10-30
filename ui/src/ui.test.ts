// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { fetchInbox, inboxBadge, messagesUrl, unreadCount } from "./Inbox";
import { appEntryUrl, appsWithPlatform, SuiteShell } from "./SuiteShell";
import { appIdFor, APP_GLYPHS, APP_IDS } from "./appMarks";
import { helpTree } from "./HelpBrowser";
import { applyTheme, setTheme, THEME_KEY, themeChoice } from "./theme";
import { BRAND_COLORS, plotTheme } from "./brandTheme";

/** WCAG contrast of two "#rrggbb" colours. */
function contrast(a: string, b: string): number {
  const lum = (hex: string) => {
    const [r, g, bl] = [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
  };
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

describe("chart tooltips", () => {
  it("read in both themes: the theme's surface behind the theme's text", () => {
    for (const theme of ["light", "dark"] as const) {
      const hover = plotTheme(theme).hoverlabel;
      expect(hover.bgcolor).toBe(BRAND_COLORS[theme].surface);
      expect(contrast(hover.bgcolor, hover.font.color)).toBeGreaterThan(4.5);
    }
  });
});

describe("helpTree", () => {
  it("files guides into nested folders in the order they came", () => {
    const tree = helpTree([
      { id: "a", title: "Start", category: "Getting started" },
      { id: "b", title: "Spikes", category: "Methods/Data quality" },
      { id: "c", title: "Stiction", category: "Methods / Loops" },
      { id: "d", title: "Loose" },
    ]);
    expect(tree.docs.map((doc) => doc.id)).toEqual(["d"]);
    expect(tree.folders.map((folder) => folder.name)).toEqual(["Getting started", "Methods"]);
    expect(tree.folders[1].folders.map((folder) => folder.path)).toEqual(["Methods/Data quality", "Methods/Loops"]);
  });
});

describe("theme", () => {
  it("defaults to the system and keeps a choice on <html>", () => {
    window.localStorage.removeItem(THEME_KEY);
    expect(themeChoice()).toBe("system");
    setTheme("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(themeChoice()).toBe("dark");
    setTheme("system");
    expect(document.documentElement.dataset.theme).toBeUndefined();
    window.localStorage.setItem(THEME_KEY, "neon");
    applyTheme();
    expect(document.documentElement.dataset.theme).toBeUndefined();
  });
});

describe("app marks", () => {
  it("draws LinkCraft and maps every id to itself", () => {
    expect(APP_GLYPHS.linkcraft.length).toBeGreaterThan(0);
    for (const id of APP_IDS) expect(appIdFor(id)).toBe(id);
  });
});

describe("inbox", () => {
  it("caps the badge and hides it at zero", () => {
    expect(inboxBadge(0)).toBe("");
    expect(inboxBadge(null)).toBe("");
    expect(inboxBadge(7)).toBe("7");
    expect(inboxBadge(99)).toBe("99");
    expect(inboxBadge(100)).toBe("99+");
  });

  it("counts unread chats and notifications together", () => {
    expect(unreadCount(null)).toBe(0);
    expect(unreadCount({ unread_messages: 2, open_actions: 0, messages_url: "/messages", actions_url: "/actions" })).toBe(2);
    expect(unreadCount({ unread_messages: 2, unread_notifications: 3, open_actions: 0, messages_url: "/messages", actions_url: "/actions" })).toBe(5);
  });

  it("opens PlantCraft's Messages page from the suite's apps", () => {
    expect(messagesUrl([])).toBe("/messages");
    expect(messagesUrl([{ id: "processcraft", name: "PlantCraft", url: "/" }])).toBe("/messages");
    expect(messagesUrl([{ id: "linkcraft", name: "LinkCraft", url: "/link/" }, { id: "processcraft", name: "PlantCraft", url: "/pc" }])).toBe("/pc/messages");
  });

  it("reads the inbox and is silent when PlantCraft has none", async () => {
    const answer = (status: number, body: unknown) => vi.fn(async () => new Response(JSON.stringify(body), { status }));
    vi.stubGlobal("fetch", answer(200, { unread_messages: 3, open_actions: 1, messages_url: "/messages", actions_url: "/actions" }));
    expect(await fetchInbox()).toEqual({ unread_messages: 3, open_actions: 1, messages_url: "/messages", actions_url: "/actions" });
    vi.stubGlobal("fetch", answer(404, { detail: "Not Found" }));
    expect(await fetchInbox()).toBeNull();
    vi.stubGlobal("fetch", answer(401, { detail: "Sign in" }));
    expect(await fetchInbox()).toBeNull();
    vi.stubGlobal("fetch", answer(403, { detail: "Not for this account" }));
    expect(await fetchInbox()).toBe("forbidden");
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("offline"); }));
    expect(await fetchInbox()).toBeNull();
    vi.unstubAllGlobals();
  });

  it("draws the messages button with its badge and refetches when told to", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const fetchMock = vi.fn(async (url: string) => new Response(JSON.stringify(url.endsWith("/inbox") ? { unread_messages: 120, unread_notifications: 3, open_actions: 0, messages_url: "/messages", actions_url: "/actions" } : []), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const opened = vi.fn();
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    const shell = (refresh: number, inbox = true) => createElement(SuiteShell, { app: "processcraft", nav: [], path: "/", href: (to: string) => to, navigate: () => undefined, user: { name: "Ana Lima" }, onSignOut: () => undefined, apps: [{ id: "processcraft", name: "PlantCraft", url: "/" }], inbox, onOpenMessages: opened, inboxRefresh: refresh }, "page");
    await act(async () => root.render(shell(0)));
    const button = host.querySelector<HTMLAnchorElement>("a.pcs-inbox");
    expect(button?.getAttribute("href")).toBe("/messages");
    expect(button?.querySelector(".pcs-badge")?.textContent).toBe("99+");
    // Unread messages lead the tab title.
    expect(document.title.startsWith("(99+) ")).toBe(true);
    // It opens Messages over the page, in every app: PlantCraft's page in a panel.
    await act(async () => button?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 })));
    expect(opened).not.toHaveBeenCalled();
    expect(document.querySelector(".pc-messages-drawer iframe")?.getAttribute("src")).toBe("/messages?embed=1");
    expect(button?.classList.contains("pcs-active")).toBe(true);
    await act(async () => { window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })); });
    expect(document.querySelector(".pc-messages-drawer[role=dialog]")).toBeNull();
    // Notifications have their own quick button and count (round 8), and open their own panel.
    const notices = host.querySelector<HTMLAnchorElement>("a.pcs-notifications");
    expect(notices?.getAttribute("href")).toBe("/messages/notifications");
    expect(notices?.querySelector(".pcs-badge")?.textContent).toBe("3");
    await act(async () => notices?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 })));
    const noticePanel = document.querySelector(".pc-messages-drawer[role=dialog]");
    expect(noticePanel?.getAttribute("aria-label")).toBe("Notifications");
    expect(noticePanel?.querySelector("iframe")?.getAttribute("src")).toBe("/messages/notifications?embed=1");
    expect(notices?.classList.contains("pcs-active")).toBe(true);
    expect(button?.classList.contains("pcs-active")).toBe(false);
    await act(async () => { window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })); });
    const calls = () => fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/inbox")).length;
    const before = calls();
    await act(async () => root.render(shell(1)));
    expect(calls()).toBe(before + 1);
    await act(async () => root.render(shell(1, false)));
    expect(host.querySelector("a.pcs-inbox")).toBeNull();
    vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(url.endsWith("/inbox") ? "{}" : "[]", { status: url.endsWith("/inbox") ? 403 : 200 })));
    await act(async () => root.render(shell(2)));
    expect(host.querySelector("a.pcs-inbox")).toBeNull();
    vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(url.endsWith("/inbox") ? "{}" : "[]", { status: url.endsWith("/inbox") ? 404 : 200 })));
    await act(async () => root.render(shell(3)));
    expect(host.querySelector("a.pcs-inbox .pcs-badge")).toBeNull();
    expect(host.querySelector("a.pcs-inbox")).not.toBeNull();
    await act(async () => root.unmount());
    vi.unstubAllGlobals();
  });
});

describe("sidebar", () => {
  it("always lists Desk first and PlantCraft last in the Apps, once each", () => {
    expect(appsWithPlatform([]).map((entry) => [entry.id, entry.url])).toEqual([["desk", "/"], ["processcraft", "/"]]);
    const link = { id: "linkcraft", name: "PlantCraft Analytics", url: "/link/" };
    expect(appsWithPlatform([link]).map((entry) => entry.id)).toEqual(["desk", "linkcraft", "processcraft"]);
    const platform = { id: "processcraft", name: "PlantCraft", url: "/pc/" };
    // Desk is served by the platform, wherever the platform is.
    expect(appsWithPlatform([link, platform])).toEqual([{ id: "desk", name: "Desk", url: "/pc/" }, link, platform]);
    expect(appEntryUrl(platform)).toBe("/pc/admin");
    expect(appEntryUrl(link)).toBe("/link/");
  });

  it("lists the apps in the order they are used: Desk, Historian first, View, PlantCraft last", () => {
    const app = (id: string) => ({ id, name: id, url: `/${id}/` });
    const listed = [app("dashcraft"), app("linkcraft"), app("other"), app("histcraft"), app("modelcraft"), app("alarmcraft")];
    expect(appsWithPlatform(listed).map((entry) => entry.id)).toEqual(["desk", "histcraft", "linkcraft", "modelcraft", "alarmcraft", "dashcraft", "other", "processcraft"]);
  });

  it("opens the apps from the app's name, keeps the fold button last in the quick row and Help in the person's menu", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 404 })));
    window.localStorage.removeItem("plantcraft-ui:sidebar");
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    const navigate = vi.fn();
    const nav = [{ to: "/", label: "Overview", icon: null }];
    const shell = (app: "processcraft" | "linkcraft") => createElement(SuiteShell, { app, nav, path: "/", href: (to: string) => to, navigate, user: { name: "Ana Lima" }, onSignOut: () => undefined, apps: [{ id: "linkcraft", name: "PlantCraft Analytics", url: "/link/" }] }, "page");
    await act(async () => root.render(shell("linkcraft")));
    const sidebar = host.querySelector("aside")!;
    // The fold button is the last of the quick buttons, never at the top.
    expect(sidebar.querySelector(".pcs-sidebar-top .pcs-fold")).toBeNull();
    expect(sidebar.querySelector(".pcs-quick > :last-child")?.getAttribute("aria-label")).toBe("Collapse the menu");
    // The apps stay closed until the app's name is clicked.
    expect(sidebar.querySelectorAll(".pcs-app-item")).toHaveLength(0);
    const order = [...sidebar.querySelectorAll(".pcs-fold, .pcs-nav-item, .pcs-profile, .pcs-messages, .pcs-notifications")].map((node) => node.textContent?.trim() || node.getAttribute("aria-label"));
    expect(order).toEqual(["Overview", "Messages", "Notifications", "Collapse the menu", "ALAna Lima"]);
    const brand = sidebar.querySelector<HTMLButtonElement>(".pcs-switcher .pcs-brand")!;
    expect(brand.getAttribute("aria-label")).toBe("Switch app");
    await act(async () => brand.click());
    // The list floats under the app's name, placed on the screen, not inside the sidebar's width.
    const pop = sidebar.querySelector<HTMLElement>(".pcs-switcher-pop")!;
    expect(pop.style.top).not.toBe("");
    expect(pop.style.left).not.toBe("");
    const apps = [...sidebar.querySelectorAll<HTMLAnchorElement>(".pcs-app-item")];
    expect(apps.map((node) => node.textContent)).toEqual(["Desk", "Analytics", "PlantCraft"]);
    expect(apps.map((node) => node.getAttribute("href"))).toEqual(["/", "/link/", "/admin"]);
    expect(apps.map((node) => node.getAttribute("aria-current"))).toEqual([null, "page", null]);
    // PlantCraft is set apart, last.
    expect(sidebar.querySelector(".pcs-switcher-pop hr + .pcs-app-item")?.textContent).toBe("PlantCraft");
    // The current app's entry goes to its first page in place and closes the menu.
    await act(async () => apps[1].dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 })));
    expect(navigate).toHaveBeenCalledWith("/");
    expect(sidebar.querySelector(".pcs-switcher-pop")).toBeNull();
    // Escape and a click outside close it too.
    await act(async () => brand.click());
    await act(async () => { window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })); });
    expect(sidebar.querySelector(".pcs-switcher-pop")).toBeNull();
    await act(async () => root.render(shell("processcraft")));
    await act(async () => sidebar.querySelector<HTMLButtonElement>(".pcs-switcher .pcs-brand")!.click());
    expect(sidebar.querySelector(".pcs-app-item.pcs-active")?.textContent).toBe("PlantCraft");
    await act(async () => document.body.dispatchEvent(new MouseEvent("mousedown", { bubbles: true })));
    expect(sidebar.querySelector(".pcs-switcher-pop")).toBeNull();
    // Folded: the same button in the same place; the [ key folds and unfolds as well.
    await act(async () => sidebar.querySelector<HTMLButtonElement>(".pcs-fold")!.click());
    expect(host.querySelector(".pcs-shell")?.classList.contains("pcs-collapsed")).toBe(true);
    expect(sidebar.querySelector(".pcs-quick .pcs-fold")?.getAttribute("aria-label")).toBe("Expand the menu");
    expect(window.localStorage.getItem("plantcraft-ui:sidebar")).toBe("collapsed");
    await act(async () => { window.dispatchEvent(new KeyboardEvent("keydown", { key: "[" })); });
    expect(host.querySelector(".pcs-shell")?.classList.contains("pcs-collapsed")).toBe(false);
    await act(async () => { window.dispatchEvent(new KeyboardEvent("keydown", { key: "[" })); });
    expect(host.querySelector(".pcs-shell")?.classList.contains("pcs-collapsed")).toBe(true);
    // One Help for the suite, in the person's menu, open at this app's guides.
    expect(sidebar.querySelector(".pcs-nav-help")).toBeNull();
    // The menu opens beside the sidebar: its arrow points right, and back while open.
    expect(sidebar.querySelector(".pcs-profile .pcs-profile-chevron")?.classList.contains("pcs-turned-back")).toBe(false);
    await act(async () => sidebar.querySelector<HTMLButtonElement>(".pcs-profile")!.click());
    expect(sidebar.querySelector(".pcs-profile .pcs-profile-chevron")?.classList.contains("pcs-turned-back")).toBe(true);
    const help = [...host.querySelectorAll<HTMLAnchorElement>(".pcs-user-pop a")].find((node) => node.textContent === "Help");
    expect(help?.getAttribute("href")).toBe("/help?app=processcraft");
    // Theme on top, then the person's pages, Help and Sign out; no About.
    const menu = host.querySelector(".pcs-user-pop")!;
    expect(menu.firstElementChild?.textContent).toBe("Theme");
    const items = [...menu.querySelectorAll("[role=menuitem]")].map((node) => node.textContent);
    expect(items.indexOf("Help")).toBeLessThan(items.indexOf("Sign out"));
    expect(items).not.toContain("About");
    expect(host.querySelector(".pcs-user-pop")).not.toBeNull();
    await act(async () => document.body.dispatchEvent(new MouseEvent("mousedown", { bubbles: true })));
    expect(host.querySelector(".pcs-user-pop")).toBeNull();
    window.localStorage.removeItem("plantcraft-ui:sidebar");
    await act(async () => root.unmount());
    vi.unstubAllGlobals();
  });
});

describe("the published modules", () => {
  it("import each other with a .js extension, as Node's ESM loader needs", async () => {
    const { readdirSync, readFileSync } = await import("node:fs");
    // vitest runs in ui/, so the sources are in src/.
    const dir = `${process.cwd()}/src/`;
    const bare: string[] = [];
    for (const name of readdirSync(dir)) {
      if (!/\.tsx?$/.test(name) || /\.test\.tsx?$/.test(name)) continue;
      const text = readFileSync(dir + name, "utf8");
      for (const match of text.matchAll(/from\s+"(\.{1,2}\/[^"]+)"/g)) {
        if (!/\.(js|css)$/.test(match[1])) bare.push(`${name}: ${match[1]}`);
      }
    }
    expect(bare).toEqual([]);
  });
  it("draws a heading over each group of the menu", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 404 })));
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    const nav = [
      { to: "/", label: "Home", icon: null, section: "Work" },
      { to: "/assets", label: "Assets", icon: null, section: "Work" },
      { to: "/users", label: "Users", icon: null, section: "Administration" },
    ];
    await act(async () => root.render(createElement(SuiteShell, { app: "processcraft", nav, path: "/", href: (to: string) => to, navigate: () => undefined, user: null, onSignOut: () => undefined, apps: [] }, "page")));
    const order = [...host.querySelectorAll(".pcs-nav[aria-label] > .pcs-nav-heading, .pcs-nav[aria-label] > .pcs-nav-item")].slice(0, 5).map((node) => `${node.className.includes("heading") ? "#" : ""}${node.textContent?.trim()}`);
    expect(order).toEqual(["#Work", "Home", "Assets", "#Administration", "Users"]);
    await act(async () => root.unmount());
    vi.unstubAllGlobals();
  });
});

describe("search and queues in the frame", () => {
  it("opens the search on Ctrl+K and shows the queue line only when an app queues work", async () => {
    const now = { at: "2026-10-23T12:00:00Z", queued: 12, running: 4, workers: 4, busy: 4, done: 0, failed: 0, cancelled: 0, done_hour: 30, failed_hour: 0, cancelled_hour: 0, skipped_hour: 0, delay_seconds: 60, average_seconds: 2, cpu_percent: null, memory_mb: null };
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/link/api/queue?window=1h") return new Response(JSON.stringify({ format: "plantcraft-queue/1", now, history: [] }));
      if (url.startsWith("/link/api/search")) return new Response(JSON.stringify({ format: "plantcraft-search/1", items: [{ title: "loop_health", type: "Algorithm", href: "/algorithms/loop_health" }] }));
      return new Response("{}", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    const navigate = vi.fn();
    const shell = createElement(SuiteShell, { app: "processcraft", nav: [], path: "/", href: (to: string) => to, navigate, user: { name: "Ana Lima" }, onSignOut: () => undefined, apps: [{ id: "processcraft", name: "PlantCraft", url: "/" }, { id: "linkcraft", name: "PlantCraft Analytics", url: "/link/" }] }, "page");
    await act(async () => root.render(shell));
    // The fourth quick button (round 8): what runs and waits, and a panel with each app's numbers.
    const queue = host.querySelector<HTMLButtonElement>(".pcs-quick .pcs-queue-button");
    expect(queue?.getAttribute("aria-label")).toContain("4 running · 12 waiting");
    expect(queue?.querySelector(".pcs-badge")?.textContent).toBe("16");
    await act(async () => queue!.click());
    const panel = document.querySelector(".pc-queue-panel[role=dialog]");
    expect(panel?.getAttribute("aria-label")).toBe("Queues");
    // The apps first; an app opened lists its work and links to its own page.
    const app = panel?.querySelector<HTMLButtonElement>(".pc-queue-app");
    expect(app?.getAttribute("aria-expanded")).toBe("false");
    expect(panel?.querySelector(".pc-queue-open")).toBeNull();
    await act(async () => app!.click());
    expect(app?.getAttribute("aria-expanded")).toBe("true");
    expect(panel?.querySelector(".pc-queue-open")?.getAttribute("href")).toBe("/link/executions");
    expect(panel?.querySelector(".pc-drawer-keep")?.getAttribute("href")).toBe("/executions");
    await act(async () => queue!.click());
    expect(document.querySelector(".pc-queue-panel[role=dialog]")).toBeNull();
    // PlantCraft answered 404: it is not asked for its queue again.
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/queue?window=1h")).toHaveLength(1);
    expect(host.querySelector(".pcs-search-button")).not.toBeNull();
    await act(async () => { window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true })); });
    const input = document.querySelector<HTMLInputElement>(".pcs-search input");
    expect(input).not.toBeNull();
    vi.useFakeTimers();
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
      setter.call(input, "loop");
      input!.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => { vi.advanceTimersByTime(300); });
    vi.useRealTimers();
    await act(async () => { await new Promise((done) => setTimeout(done, 10)); });
    const hit = document.querySelector<HTMLAnchorElement>(".pcs-hit");
    expect(hit?.getAttribute("href")).toBe("/link/algorithms/loop_health");
    expect(document.querySelector(".pcs-search-group h3")?.textContent).toBe("Analytics");
    await act(async () => { document.querySelector(".pcs-search")!.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
    expect(document.querySelector(".pcs-search")).toBeNull();
    await act(async () => root.unmount());
    vi.unstubAllGlobals();
  });
});
