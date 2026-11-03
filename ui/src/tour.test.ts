// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { formatAgo, formatDuration, formatNumber, formatShare } from "./format";
import { createNav } from "./nav";
import { addStatusTones, statusVar } from "./brandTheme";
import { SuiteShell, startTour } from "./SuiteShell";
import { GuidedTour, phoneCardPlace, TOURS_OFF_KEY, tourDue, tourPageFor } from "./Tour";
import { configureUi } from "./i18n";
import { TOUR_LANGUAGE_KEY, tourLanguage, tourLanguageFor, tt } from "./tourLanguage";
import { TOUR_TEXTS } from "./tourTexts";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function mount() {
  const host = document.createElement("div");
  document.body.appendChild(host);
  return { host, root: createRoot(host) };
}

const click = (node: Element | null | undefined) => node?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 }));

describe("tour card on a phone", () => {
  it("sits across the foot of what shows, also when the page is wider than the phone", () => {
    expect(phoneCardPlace({ left: 0, top: 0, width: 390, height: 844, frame: 844 })).toEqual({ left: 16, width: 358, bottom: 16, maxHeight: 812 });
    // A 594 px page: the frame is 594 x 1285, the phone shows its top left 390 x 844.
    expect(phoneCardPlace({ left: 0, top: 0, width: 390, height: 844, frame: 1285 })).toEqual({ left: 16, width: 358, bottom: 457, maxHeight: 812 });
    // Scrolled sideways: the card follows.
    expect(phoneCardPlace({ left: 204, top: 441, width: 390, height: 844, frame: 1285 })).toMatchObject({ left: 220, bottom: 16 });
  });
});

describe("tour pages", () => {
  it("never leaves the page the person opened on the first step, then follows the steps", () => {
    expect(tourPageFor(0, "/", "/admin")).toBeNull();
    expect(tourPageFor(1, "/loops", "/admin")).toBe("/loops");
    expect(tourPageFor(2, "/loops", "/loops")).toBeNull();
    expect(tourPageFor(3, undefined, "/loops")).toBeNull();
  });
});

describe("guided tour", () => {
  const steps = [
    { title: "Welcome", body: "Hello" },
    { title: "The loops", body: "Every loop", path: "/loops", target: "#loops" },
    { title: "Your apps", body: "Open one", path: "/" },
  ];

  it("opens by itself the first time, walks the pages and is not shown again", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 404 })));
    window.localStorage.clear();
    const { host, root } = mount();
    const navigate = vi.fn();
    const shell = (path: string) => createElement(SuiteShell, { app: "linkcraft", nav: [], path, href: (to: string) => to, navigate, user: { name: "Ana" }, onSignOut: () => undefined, apps: [], inbox: false, tour: steps }, createElement("div", { id: "loops" }, "loops"));
    await act(async () => root.render(shell("/")));
    expect(host.querySelector(".pct-card h2")?.textContent).toBe("Welcome");
    expect(host.querySelector(".pct-count")?.textContent).toBe("Step 1 of 3");
    await act(async () => click(host.querySelector(".pct-card .button-primary")));
    expect(host.querySelector(".pct-card h2")?.textContent).toBe("The loops");
    expect(navigate).toHaveBeenCalledWith("/loops");
    await act(async () => root.render(shell("/loops")));
    await act(async () => click(host.querySelector(".pct-card .button-primary")));
    expect(navigate).toHaveBeenLastCalledWith("/");
    expect(host.querySelector(".pct-card .button-primary")?.textContent).toContain("Finish");
    await act(async () => click(host.querySelector(".pct-card .button-primary")));
    expect(host.querySelector(".pct-card")).toBeNull();
    expect(tourDue("linkcraft")).toBe(false);
    // Seen: a new visit does not open it; the user menu and startTour() do.
    await act(async () => root.unmount());
    const again = mount();
    await act(async () => again.root.render(shell("/")));
    expect(again.host.querySelector(".pct-card")).toBeNull();
    await act(async () => click(again.host.querySelector(".pcs-profile")));
    const item = [...again.host.querySelectorAll(".pcs-user-pop button")].find((node) => node.textContent === "Take the tour");
    await act(async () => click(item));
    expect(again.host.querySelector(".pct-card h2")?.textContent).toBe("Welcome");
    await act(async () => window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })));
    expect(again.host.querySelector(".pct-card")).toBeNull();
    await act(async () => startTour());
    expect(again.host.querySelector(".pct-card")).not.toBeNull();
    await act(async () => again.root.unmount());
    vi.unstubAllGlobals();
  });

  it("stays closed when tours are switched off, and without steps", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 404 })));
    window.localStorage.clear();
    window.localStorage.setItem(TOURS_OFF_KEY, "1");
    expect(tourDue("histcraft")).toBe(false);
    const { host, root } = mount();
    await act(async () => root.render(createElement(SuiteShell, { app: "histcraft", nav: [], path: "/", href: (to: string) => to, navigate: () => undefined, user: null, onSignOut: () => undefined, apps: [], inbox: false, tour: steps }, "page")));
    expect(host.querySelector(".pct-card")).toBeNull();
    window.localStorage.clear();
    await act(async () => root.render(createElement(SuiteShell, { app: "histcraft", nav: [], path: "/", href: (to: string) => to, navigate: () => undefined, user: null, onSignOut: () => undefined, apps: [], inbox: false }, "page")));
    expect(host.querySelector(".pct-card")).toBeNull();
    await act(async () => click(host.querySelector(".pcs-profile")));
    expect([...host.querySelectorAll(".pcs-user-pop button")].some((node) => node.textContent === "Take the tour")).toBe(false);
    await act(async () => root.unmount());
    vi.unstubAllGlobals();
  });
});

describe("tour language", () => {
  it("is English with no picker while translations are off", async () => {
    window.localStorage.setItem(TOUR_LANGUAGE_KEY, "pt-BR");
    expect(tourLanguage()).toBe("en");
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 404 })));
    const { host, root } = mount();
    await act(async () => root.render(createElement(SuiteShell, { app: "linkcraft", nav: [], path: "/", href: (to: string) => to, navigate: () => undefined, user: null, onSignOut: () => undefined, apps: [], inbox: false, tour: [{ title: "Welcome to Analytics", body: "x" }] }, "page")));
    expect(host.querySelector(".pct-language")).toBeNull();
    await act(async () => root.unmount());
    window.localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("starts from the browser language, and the card's picker changes and remembers it", async () => {
    configureUi({ translations: true });
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 404 })));
    window.localStorage.clear();
    expect(tourLanguageFor("pt")).toBe("pt-BR");
    expect(tourLanguageFor("de-CH")).toBe("de");
    expect(tourLanguageFor("ja")).toBeNull();
    const languages = vi.spyOn(navigator, "languages", "get").mockReturnValue(["ja", "es-AR"]);
    expect(tourLanguage()).toBe("es");
    languages.mockRestore();
    const { host, root } = mount();
    const steps = () => [{ title: tt("Welcome to Analytics"), body: "x" }, { title: tt("Signals"), body: "y" }];
    await act(async () => root.render(createElement(SuiteShell, { app: "linkcraft", nav: [], path: "/", href: (to: string) => to, navigate: () => undefined, user: null, onSignOut: () => undefined, apps: [], inbox: false, tour: steps }, "page")));
    expect(host.querySelector(".pct-card h2")?.textContent).toBe("Welcome to Analytics");
    const select = host.querySelector<HTMLSelectElement>(".pct-language select")!;
    expect([...select.options].map((option) => option.value)).toEqual(["en", "pt-BR", "es", "fr", "de"]);
    await act(async () => {
      select.value = "pt-BR";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(host.querySelector(".pct-card h2")?.textContent).toBe("Boas-vindas ao Analytics");
    expect(host.querySelector(".pct-count")?.textContent).toBe("Passo 1 de 2");
    expect(window.localStorage.getItem(TOUR_LANGUAGE_KEY)).toBe("pt-BR");
    await act(async () => root.unmount());
    window.localStorage.clear();
    vi.unstubAllGlobals();
    configureUi({ translations: false });
  });

  it("has every tour text in every language", () => {
    const english = Object.keys(TOUR_TEXTS["pt-BR"]).sort();
    for (const code of ["es", "fr", "de"]) expect(Object.keys(TOUR_TEXTS[code]).sort()).toEqual(english);
  });
});

describe("shared helpers", () => {
  it("maps app paths under the base path", () => {
    const nav = createNav("/link/");
    expect(nav.href("/loops/x")).toBe("/link/loops/x");
    expect(nav.href("loops")).toBe("/link/loops");
    expect(nav.appPath("/link/loops/x")).toBe("/loops/x");
    expect(nav.appPath("/link")).toBe("/");
    expect(createNav("/").href("/runs")).toBe("/runs");
  });

  it("writes numbers, shares, durations and ages", () => {
    expect(formatNumber(1234.56)).toBe("1,234.6");
    expect(formatNumber(Number.NaN)).toBe("—");
    expect(formatShare(0.256)).toBe("26%");
    expect(formatDuration(30)).toBe("30 s");
    expect(formatDuration(600)).toBe("10 min");
    const now = Date.parse("2026-10-20T12:00:00Z");
    expect(formatAgo("2026-10-20T11:45:00Z", now)).toBe("15 min ago");
    expect(formatAgo("2026-10-20 09:00:00", now)).toBe("3 h ago");
  });

  it("colours a status by its tone, with the app's own ids added", () => {
    expect(statusVar("failed", "text")).toBe("var(--pc-problem-text)");
    expect(statusVar("never-heard")).toBe("var(--pc-inactive-fill)");
    addStatusTones({ drifting: "attention" });
    expect(statusVar("drifting")).toBe("var(--pc-attention-fill)");
  });
});

describe("a step's onShow", () => {
  it("runs once per step, even when the steps are built again while it shows", () => {
    vi.useFakeTimers();
    const { host, root } = mount();
    const undo = vi.fn();
    const shown = vi.fn(() => undo);
    // Each render builds new steps, as a shell does with a tour function.
    const steps = () => [{ path: "/", title: "Panel", body: null, onShow: () => shown() }, { path: "/", title: "Next", body: null }];
    const draw = () => root.render(createElement(GuidedTour, { app: "processcraft", steps: steps(), path: "/", navigate: () => undefined, onClose: () => undefined }));
    act(() => draw());
    act(() => { vi.advanceTimersByTime(800); });
    act(() => draw());
    act(() => draw());
    act(() => { vi.advanceTimersByTime(800); });
    expect(shown).toHaveBeenCalledTimes(1);
    expect(undo).not.toHaveBeenCalled();
    act(() => root.unmount());
    expect(undo).toHaveBeenCalledTimes(1);
    host.remove();
    vi.useRealTimers();
  });
});
