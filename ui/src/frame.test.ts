// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppFrames, withoutFrameQuery } from "./AppFrames";
import { appPrefix, forgetFramed, frameOff, readToFrame, sanitizeIcon, type FrameState } from "./frame";
import { SuiteShell } from "./SuiteShell";

afterEach(() => { forgetFramed(); vi.unstubAllGlobals(); document.body.innerHTML = ""; });

describe("the frame's addresses", () => {
  it("finds the app of an address, longest prefix first, never the platform's root", () => {
    const bases = ["/", "/link/", "/link-extra/", "/dash/"];
    expect(appPrefix("/link/loops/3", bases)).toBe("/link/");
    expect(appPrefix("/link", bases)).toBe("/link/");
    expect(appPrefix("/link-extra/x", bases)).toBe("/link-extra/");
    expect(appPrefix("/admin", bases)).toBeNull();
    expect(appPrefix("/", bases)).toBeNull();
  });

  it("opens an app on its own page and leaves the frame's query out of the address", () => {
    expect(frameOff("/link/loops")).toBe("/link/loops?pc-frame=off");
    expect(frameOff("/link/loops?q=1#top")).toBe("/link/loops?q=1&pc-frame=off#top");
    expect(withoutFrameQuery("/link/loops?q=1&pc-frame=off#top")).toBe("/link/loops?q=1#top");
    expect(withoutFrameQuery("/link/loops?pc-frame=off")).toBe("/link/loops");
    expect(withoutFrameQuery("/link/loops")).toBe("/link/loops");
  });
});

describe("icons the apps send", () => {
  it("keeps shapes and their geometry, drops scripts, events, links and foreign elements", () => {
    const clean = sanitizeIcon('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" onload="alert(1)" stroke="currentColor"><path d="M1 1h2" onclick="x()"/><script>alert(1)</script><a href="javascript:x()"><circle r="2"/></a><foreignObject><div/></foreignObject><rect fill="url(http://x)" width="2"/></svg>');
    expect(clean).toContain("viewBox=\"0 0 24 24\"");
    expect(clean).toContain("<path d=\"M1 1h2\"");
    expect(clean).not.toMatch(/onload|onclick|script|<a|foreignObject|url\(/i);
    expect(sanitizeIcon("<div>not an icon</div>")).toBe("");
    expect(sanitizeIcon("")).toBe("");
  });
});

describe("only the suite's own messages", () => {
  it("reads a known message from the same origin, nothing else", () => {
    const same = new MessageEvent("message", { origin: window.location.origin, data: { type: "pc-frame:ready" } });
    expect(readToFrame(same)?.type).toBe("pc-frame:ready");
    expect(readToFrame(new MessageEvent("message", { origin: "https://elsewhere.example", data: { type: "pc-frame:ready" } }))).toBeNull();
    expect(readToFrame(new MessageEvent("message", { origin: window.location.origin, data: { type: "pc-frame:go", to: "/" } }))).toBeNull();
    expect(readToFrame(new MessageEvent("message", { origin: window.location.origin, data: "pc-frame:ready" }))).toBeNull();
  });
});

const state = (patch: Partial<FrameState> = {}): FrameState => ({ app: "linkcraft", base: "/link/", home: "/", path: "/", url: "/link/", nav: [], heading: "", tour: false, assistant: true, assistantOpen: false, ...patch });

describe("an app inside the frame", () => {
  it("draws only its pages and tells the frame its sidebar, then does what the frame asks", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 404 })));
    forgetFramed(true);
    const posted: unknown[] = [];
    const listen = (event: MessageEvent) => posted.push(event.data);
    window.addEventListener("message", listen);
    const navigate = vi.fn();
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    const icon = createElement("svg", { viewBox: "0 0 24 24" }, createElement("path", { d: "M1 1h2" }));
    await act(async () => root.render(createElement(SuiteShell, { app: "linkcraft", nav: [{ to: "/", label: "Overview", icon }, { to: "/loops", label: "Loops", icon }], path: "/loops", href: (to: string) => `/link${to}`, navigate, user: { name: "Ana" }, onSignOut: () => undefined }, createElement("h1", null, "FIC-101"))));
    await act(async () => { await new Promise((done) => setTimeout(done, 10)); });
    expect(host.querySelector(".pcs-sidebar")).toBeNull();
    expect(host.querySelector(".pcs-framed main h1")?.textContent).toBe("FIC-101");
    const sent = posted.filter((item) => (item as { type?: string }).type === "pc-frame:state").at(-1) as { state: FrameState };
    expect(posted.some((item) => (item as { type?: string }).type === "pc-frame:ready")).toBe(true);
    expect(sent.state.base).toBe("/link/");
    expect(sent.state.heading).toBe("FIC-101");
    expect(sent.state.nav.map((item) => [item.label, item.href, item.active])).toEqual([["Overview", "/link/", false], ["Loops", "/link/loops", true]]);
    expect(sent.state.nav[1].icon).toContain("<path");
    // The frame's sidebar asks for a page.
    await act(async () => { window.dispatchEvent(new MessageEvent("message", { origin: window.location.origin, source: window, data: { type: "pc-frame:go", to: "/overview" } })); });
    expect(navigate).toHaveBeenCalledWith("/overview");
    // Shortcuts go to the frame.
    posted.length = 0;
    await act(async () => { window.dispatchEvent(new KeyboardEvent("keydown", { key: "[" })); await new Promise((done) => setTimeout(done, 0)); });
    expect(posted).toContainEqual({ type: "pc-frame:key", key: "[" });
    window.removeEventListener("message", listen);
    await act(async () => root.unmount());
  });
});

describe("the frame", () => {
  it("shows an app once it is ready, follows what it reports, and keeps it loaded behind PlantCraft's pages", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const onState = vi.fn();
    const onAddress = vi.fn();
    const onOpen = vi.fn();
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    const frames = (active: boolean, url = "/link/") => createElement(AppFrames, { active, url, prefix: "/link/", onState, onAddress, onOpen, onKey: () => undefined });
    await act(async () => root.render(frames(true)));
    const frame = host.querySelector<HTMLIFrameElement>("iframe[data-pc-frame]")!;
    expect(frame.getAttribute("src")).toBe("/link/");
    expect(frame.hasAttribute("data-ready")).toBe(false);
    expect(host.querySelector(".pcs-frame-loading")).not.toBeNull();
    const from = (data: unknown) => window.dispatchEvent(new MessageEvent("message", { origin: window.location.origin, source: frame.contentWindow, data }));
    await act(async () => { from({ type: "pc-frame:state", state: state({ path: "/loops", url: "/link/loops" }) }); });
    expect(frame.hasAttribute("data-ready")).toBe(true);
    expect(onState).toHaveBeenLastCalledWith(expect.objectContaining({ path: "/loops" }));
    expect(onAddress).toHaveBeenCalledWith("/link/loops");
    // A link out of the app is opened by the frame; one to the app's own prefix never loops.
    await act(async () => { from({ type: "pc-frame:open", url: "/assets/FIC-101" }); });
    expect(onOpen).toHaveBeenCalledWith("/assets/FIC-101");
    // Another window's messages are not the app's.
    await act(async () => { window.dispatchEvent(new MessageEvent("message", { origin: window.location.origin, source: window, data: { type: "pc-frame:open", url: "/x" } })); });
    expect(onOpen).toHaveBeenCalledTimes(1);
    // On a PlantCraft page the app stays loaded, hidden.
    await act(async () => root.render(frames(false, "/link/loops")));
    expect(host.querySelector(".pcs-frames")?.hasAttribute("hidden")).toBe(true);
    expect(host.querySelector("iframe[data-pc-frame]")).toBe(frame);
    await act(async () => root.unmount());
  });
});
