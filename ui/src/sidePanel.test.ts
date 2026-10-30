// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Heading } from "./Blocks.js";
import { closeMessages } from "./MessagesDrawer.js";
import { clickedOutside } from "./dismiss.js";
import { claimPanel, markPanelSwap, otherPanelOpen, panelSwapping, PANEL_SWAP_MS, registerPanel, setOutsidePanel, SidePanel } from "./SidePanel.js";
import { closeQueues, queueLook, type SuiteQueueTotals } from "./SuiteQueue.js";
import { SuiteShell } from "./SuiteShell.js";

afterEach(() => {
  act(() => { closeMessages(); closeQueues(); });
  setOutsidePanel("assistant", false);
  markPanelSwap(0);
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("one panel at a time, swapped in place (round 8)", () => {
  it("swaps only when another panel was open, here or in the app inside the frame", () => {
    let queues = false;
    registerPanel("queues", () => { queues = false; }, () => queues);
    claimPanel("messages");
    expect(panelSwapping()).toBe(false); // nothing was open: the panel slides in
    queues = true;
    expect(otherPanelOpen("messages")).toBe(true);
    claimPanel("messages");
    expect(queues).toBe(false);
    expect(panelSwapping()).toBe(true);
    expect(panelSwapping(Date.now() + PANEL_SWAP_MS + 1)).toBe(false);
    // The app's assistant, open inside the frame's iframe, counts as an open panel.
    markPanelSwap(0);
    setOutsidePanel("assistant", true);
    expect(otherPanelOpen("messages")).toBe(true);
    expect(otherPanelOpen("assistant")).toBe(false);
    claimPanel("messages");
    expect(panelSwapping()).toBe(true);
  });
});

describe("the work queues' button", () => {
  const totals = (over: Partial<SuiteQueueTotals>): SuiteQueueTotals => ({ queued: 0, running: 0, workers: 4, failedHour: 0, delaySeconds: 0, late: false, ...over });
  it("turns while work runs, goes green when it finished well, red after a failure until seen", () => {
    const quiet = { unseenFailures: false, justDone: false };
    expect(queueLook(totals({}), quiet)).toBe("idle");
    expect(queueLook(totals({ queued: 3 }), quiet)).toBe("waiting");
    expect(queueLook(totals({ running: 2, queued: 3 }), quiet)).toBe("running");
    expect(queueLook(totals({}), { unseenFailures: false, justDone: true })).toBe("done");
    expect(queueLook(totals({ queued: 3, late: true }), quiet)).toBe("late");
    expect(queueLook(totals({ running: 2, failedHour: 1 }), { unseenFailures: true, justDone: false })).toBe("failed");
    // Failures already seen in the panel no longer turn it red.
    expect(queueLook(totals({ failedHour: 1 }), quiet)).toBe("idle");
  });
});

describe("the page's top", () => {
  it("is the title and the buttons only: nothing above or under the title", () => {
    const html = renderToStaticMarkup(createElement(Heading, { eyebrow: "Link", title: "Loops", detail: "Every loop of the plant.", actions: createElement("button", null, "New loop") }));
    expect(html).toBe('<div class="page-heading"><div class="page-heading-title"><h1>Loops</h1></div><div class="heading-actions"><button>New loop</button></div></div>');
  });
});

describe("the quick buttons", () => {
  it("close their panel on a second click, and every panel closes on another page", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/inbox") return new Response(JSON.stringify({ unread_messages: 2, unread_notifications: 5, open_actions: 0, messages_url: "/messages", actions_url: "/actions" }));
      return new Response("{}", { status: 404 });
    }));
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    const shell = (path: string) => createElement(SuiteShell, { app: "processcraft", nav: [{ to: "/", label: "Overview", icon: null }, { to: "/assets", label: "Assets", icon: null }], path, href: (to: string) => to, navigate: () => undefined, user: { name: "Ana Lima" }, onSignOut: () => undefined, apps: [], assistant: false }, "page");
    await act(async () => root.render(shell("/")));
    await act(async () => { await Promise.resolve(); });
    const messages = host.querySelector<HTMLAnchorElement>(".pcs-quick .pcs-messages")!;
    const notices = host.querySelector<HTMLAnchorElement>(".pcs-quick .pcs-notifications")!;
    // Their counts, as numbers on the buttons.
    expect(messages.querySelector(".pcs-badge")?.textContent).toBe("2");
    expect(notices.querySelector(".pcs-badge")?.textContent).toBe("5");
    const click = (node: HTMLElement) => act(async () => { node.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 })); });
    await click(messages);
    expect(document.querySelector("[role=dialog][aria-label=Messages]")).not.toBeNull();
    // Messages to Notifications: the same panel, its content swapped.
    await click(notices);
    expect(document.querySelector("[role=dialog][aria-label=Notifications]")).not.toBeNull();
    expect(document.querySelectorAll(".pc-side-panel")).toHaveLength(1);
    await click(notices);
    expect(document.querySelector("[role=dialog]")).toBeNull();
    // Open, then go to another page: it closes.
    await click(messages);
    expect(document.querySelector("[role=dialog][aria-label=Messages]")).not.toBeNull();
    await act(async () => root.render(shell("/assets")));
    expect(document.querySelector("[role=dialog]")).toBeNull();
    await act(async () => root.unmount());
  });
});

describe("what floats closes on a click outside it", () => {
  it("closes a panel on a click on the page or into an iframe, not on the quick buttons or its own pickers", async () => {
    vi.useFakeTimers();
    const host = document.createElement("div");
    document.body.innerHTML = '<div class="pcs-quick"><button id="quick">Q</button></div><main id="page"><iframe id="app"></iframe></main><div role="listbox" id="picker"></div>';
    document.body.appendChild(host);
    const root = createRoot(host);
    let closed = 0;
    await act(async () => root.render(createElement(SidePanel, { label: "Work queues", onClose: () => { closed += 1; } }, createElement("p", { id: "inside" }, "x"))));
    const down = (id: string) => act(() => { document.getElementById(id)!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true })); });
    down("inside");
    down("quick");
    down("picker");
    expect(closed).toBe(0);
    down("page");
    expect(closed).toBe(1);
    // A click into the app's iframe only blurs this window; the iframe has the focus after.
    const frame = document.getElementById("app") as HTMLIFrameElement;
    frame.focus();
    vi.spyOn(document, "activeElement", "get").mockReturnValue(frame);
    act(() => { window.dispatchEvent(new Event("blur")); vi.runAllTimers(); });
    expect(closed).toBe(2);
    await act(async () => root.unmount());
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("tells a click outside from one inside or on what keeps it open", () => {
    document.body.innerHTML = '<div id="menu"><span id="in">a</span></div><div class="pcs-quick"><b id="q">q</b></div><div role="dialog"><i id="d">d</i></div><p id="out">o</p>';
    const menu = document.getElementById("menu");
    const at = (id: string) => document.getElementById(id);
    expect(clickedOutside(menu, at("in"))).toBe(false);
    expect(clickedOutside(menu, at("out"))).toBe(true);
    expect(clickedOutside(menu, at("q"))).toBe(true);
    expect(clickedOutside(menu, at("q"), { ignore: ".pcs-quick" })).toBe(false);
    expect(clickedOutside(menu, at("d"))).toBe(true);
    expect(clickedOutside(menu, at("d"), { keepFloating: true })).toBe(false);
  });
});
