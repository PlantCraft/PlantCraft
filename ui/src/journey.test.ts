// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { FollowUp, JourneyPath, NextSteps, fetchActions, followUpRows, journeyFolded, journeyKey, journeyStates, newActionUrl, platformPath, type FollowUpAction } from "./Journey";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

async function render(element: ReturnType<typeof createElement>) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => root.render(element));
  return { host, unmount: () => act(async () => root.unmount()) };
}

const action = (id: number, status: string, extra: Partial<FollowUpAction> = {}): FollowUpAction => ({ action_id: id, title: `A${id}`, status, priority: "medium", ...extra });

describe("journey path", () => {
  it("makes the first step not done the next one, unless a step says so", () => {
    expect(journeyStates([{ title: "a", state: "done" }, { title: "b" }, { title: "c" }])).toEqual(["done", "next", "todo"]);
    expect(journeyStates([{ title: "a" }, { title: "b", state: "next" }, { title: "c", state: "info" }])).toEqual(["todo", "next", "info"]);
    expect(journeyStates([{ title: "a", state: "done" }, { title: "b", state: "done" }])).toEqual(["done", "done"]);
  });

  it("draws at most four steps, follows pages of the app in place and others by link", async () => {
    const navigate = vi.fn();
    const steps = [
      { title: "Connect", state: "done" as const, url: "/hist/sources" },
      { title: "Map", to: "/assets", value: 12, valueLabel: "assets" },
      { title: "Watch", to: "/loops" },
      { title: "Act", to: "/actions" },
      { title: "Fifth", to: "/x" },
    ];
    const { host, unmount } = await render(createElement(JourneyPath, { title: "Where to start", steps, href: (to: string) => `/link${to}`, navigate }));
    const items = [...host.querySelectorAll("li")];
    expect(items.map((item) => item.className)).toEqual(["pc-journey-step pc-journey-done", "pc-journey-step pc-journey-next", "pc-journey-step pc-journey-todo", "pc-journey-step pc-journey-todo"]);
    expect(items[1].getAttribute("aria-current")).toBe("step");
    const links = [...host.querySelectorAll<HTMLAnchorElement>("a")];
    expect(links.map((link) => link.getAttribute("href"))).toEqual(["/hist/sources", "/link/assets", "/link/loops", "/link/actions"]);
    await act(async () => links[1].dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 })));
    expect(navigate).toHaveBeenCalledWith("/assets");
    // A page elsewhere is a plain link (jsdom cannot follow it, so the test stops it at the document).
    const stop = (event: Event) => event.preventDefault();
    document.addEventListener("click", stop);
    await act(async () => links[0].dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 })));
    document.removeEventListener("click", stop);
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(host.querySelector(".pc-journey-value b")?.textContent).toBe("12");
    await unmount();
  });

  it("folds to one line, keeps the choice per page, and starts folded once every step is done", async () => {
    window.localStorage.clear();
    expect(journeyFolded(["done", "next"], null)).toBe(false);
    expect(journeyFolded(["done", "info"], null)).toBe(true);
    expect(journeyFolded(["done", "done"], false)).toBe(false);
    expect(journeyKey("/setup")).toBe("pc-journey:/setup");
    const steps = [{ title: "Connect", state: "done" as const }, { title: "Map", to: "/assets" }];
    const first = await render(createElement(JourneyPath, { title: "Routine", steps, storageKey: "/p" }));
    expect(first.host.querySelectorAll("li")).toHaveLength(2);
    const hide = first.host.querySelector<HTMLButtonElement>(".pc-journey-hide")!;
    await act(async () => hide.click());
    expect(first.host.querySelectorAll("li")).toHaveLength(0);
    expect(first.host.querySelector(".pc-journey-toggle")?.textContent).toContain("1 of 2 steps done");
    expect(window.localStorage.getItem("pc-journey:/p")).toBe("folded");
    await first.unmount();
    // The same page remembers; another page does not.
    const again = await render(createElement(JourneyPath, { title: "Routine", steps, storageKey: "/p" }));
    expect(again.host.querySelector(".pc-journey-folded")).not.toBeNull();
    await act(async () => again.host.querySelector<HTMLButtonElement>(".pc-journey-toggle")!.click());
    expect(again.host.querySelectorAll("li")).toHaveLength(2);
    await again.unmount();
    const done = await render(createElement(JourneyPath, { title: "Routine", steps: [{ title: "A", state: "done" as const }], storageKey: "/q" }));
    expect(done.host.querySelector(".pc-journey-folded")).not.toBeNull();
    await done.unmount();
    window.localStorage.clear();
  });

  it("lists the next pages and draws nothing without one", async () => {
    const { host, unmount } = await render(createElement(NextSteps, { items: [{ title: "Loops", detail: "Scores", to: "/loops" }, { title: "Nowhere" }] }));
    expect([...host.querySelectorAll("a")].map((link) => link.getAttribute("href"))).toEqual(["/loops"]);
    await unmount();
    const empty = await render(createElement(NextSteps, { items: [{ title: "Nowhere" }] }));
    expect(empty.host.innerHTML).toBe("");
    await empty.unmount();
  });
});

describe("follow-up", () => {
  it("joins PlantCraft's address and fills in the new-action form", () => {
    expect(platformPath("/", "actions")).toBe("/actions");
    expect(platformPath("/pc/", "/actions/3")).toBe("/pc/actions/3");
    expect(platformPath(null, "actions")).toBe("/actions");
    expect(newActionUrl("/", "asset:FIC-1003", "FIC-1003: Stiction")).toBe("/actions?new=1&ref=asset%3AFIC-1003&title=FIC-1003%3A+Stiction");
  });

  it("shows the open actions, then the last three closed", () => {
    const rows = followUpRows([action(1, "done", { completed_at: "2026-10-01" }), action(2, "open"), action(3, "cancelled", { updated_at: "2026-10-03" }), action(4, "done", { completed_at: "2026-10-04" }), action(5, "done", { completed_at: "2026-09-01" }), action(6, "blocked")]);
    expect(rows.open.map((item) => item.action_id)).toEqual([2, 6]);
    expect(rows.closed.map((item) => item.action_id)).toEqual([4, 3, 1]);
    expect(rows.closedTotal).toBe(4);
  });

  it("reads the actions about a reference and is silent when PlantCraft cannot answer", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ items: [action(1, "open")] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    expect(await fetchActions("asset:FIC-1003")).toHaveLength(1);
    expect(String(fetchMock.mock.calls[0]?.[0 as never])).toBe("/api/v1/actions?ref=asset%3AFIC-1003");
    await fetchActions(null, { status: ["open", "blocked"], limit: 500 });
    expect(String(fetchMock.mock.calls[1]?.[0 as never])).toBe("/api/v1/actions?status=open&status=blocked&limit=500");
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 404 })));
    expect(await fetchActions("asset:x")).toBeNull();
    vi.unstubAllGlobals();
  });

  it("draws the actions with links to PlantCraft, or hides itself", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ items: [action(7, "open", { status_label: "Open", owner_name: "Ana", due_at: "2026-10-22" })] }), { status: 200 })));
    const { host, unmount } = await render(createElement(FollowUp, { subject: "asset:FIC-1003", newTitle: "FIC-1003", platformUrl: "/", canCreate: true }));
    await act(async () => undefined);
    const links = [...host.querySelectorAll<HTMLAnchorElement>("a")].map((link) => link.getAttribute("href"));
    expect(links).toEqual(["/actions?new=1&ref=asset%3AFIC-1003&title=FIC-1003", "/actions/7"]);
    expect(host.textContent).toContain("Ana");
    await unmount();
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 403 })));
    const hidden = await render(createElement(FollowUp, { subject: "asset:x", newTitle: "x" }));
    await act(async () => undefined);
    expect(hidden.host.innerHTML).toBe("");
    await hidden.unmount();
    vi.unstubAllGlobals();
  });
});
