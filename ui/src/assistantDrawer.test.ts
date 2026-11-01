// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PANEL_OUT_MS } from "./SidePanel";
import { Heading } from "./Blocks";
import { VersionsTab } from "./Versions";
import { renderToStaticMarkup } from "react-dom/server";
import { AssistantHost, AssistantTopButton, closeAssistant, forgetAssistantStatus, pageContext, useAssistantPage, type AssistantTask } from "./AssistantDrawer";

type Call = { url: string; method: string; body: unknown };

function server(available = true, allowed = true, canSetUp = false) {
  const calls: Call[] = [];
  let polls = 0;
  const answer = { message_id: 2, role: "assistant", text: "", state: "working", steps: [], charts: [], meta: { queued: true } };
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null });
    const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
    if (url.endsWith("/api/assistant")) return json({ available, allowed, can_set_up: canSetUp, reason: available ? "" : "No language model is set up yet.", chats: [{ chat_id: 7, title: "Which loops are worst?", place: "Link › Loops", updated_at: "2026-10-24T10:00:00Z" }] });
    if (url.endsWith("/api/assistant/chats") && method === "POST") return json({ chat: { chat_id: 7 }, messages: [{ message_id: 1, role: "user", text: "Why?", state: "done", steps: [], charts: [], meta: {} }, answer] }, 201);
    if (url.endsWith("/api/assistant/chats/7") && method === "GET") { polls += 1; return json({ messages: [{ ...answer, state: "done", text: "Because the **valve** stuck.", steps: [{ tool: "get_asset", title: "Asset", summary: "asset_id: FIC-101", state: "ok" }], meta: { model: "Local · m" } }] }); }
    if (url.endsWith("/keep")) return json({ chat_id: 7, kept: true });
    if (method === "DELETE") return json({ deleted: 7 });
    return json({ detail: "no" }, 404);
  }));
  return { calls, polls: () => polls };
}

async function mount(element: ReturnType<typeof createElement>) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  await act(async () => { root.render(element); });
  await act(async () => { await Promise.resolve(); });
  return { host, root };
}

const button = (host: Element, text: string) => [...host.querySelectorAll("button")].find((item) => (item.textContent ?? "").includes(text) || item.getAttribute("aria-label")?.includes(text));

afterEach(() => { act(() => closeAssistant()); forgetAssistantStatus(); vi.useRealTimers(); vi.unstubAllGlobals(); document.body.innerHTML = ""; });

describe("the assistant's side panel", () => {
  it("opens from the top, asks what the person wants with the page's tasks, and keeps the chat", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { calls } = server();
    const opened: string[] = [];
    vi.stubGlobal("open", vi.fn((url: string) => { opened.push(url); return null; }));
    const tasks: AssistantTask[] = [
      { label: "Why is it active?", instructions: "Read the alarm's signal and say why it is active.", context: () => "Limit 80, value 92" },
      { label: "Ask about one execution", instructions: "Read that execution.", ask: "Which execution?" },
    ];
    function Page() {
      useAssistantPage({ subject: "asset:FIC-101", title: "FIC-101", place: "Alarms › FIC-101", context: "Alarm FIC-101 PV HI since 10:02", tasks });
      return null;
    }
    const page = () => ({ place: "Alarms › Active alarms", context: "page text" });
    const { host, root } = await mount(createElement("div", null,
      createElement(Page), createElement(AssistantTopButton, { platformUrl: "/", page }), createElement(AssistantHost, { platformUrl: "/", page })));
    await act(async () => { button(host, "Ask the assistant about this page")?.click(); });
    await act(async () => { await Promise.resolve(); });
    // The page's tasks first, then the suite's own.
    expect(host.querySelector(".pc-drawer-intro h3")?.textContent).toBe("What do you want to do?");
    expect([...host.querySelectorAll(".pc-drawer-tasks strong")].map((item) => item.textContent)).toEqual(["Why is it active?", "Ask about one execution", "Explain this page"]);
    await act(async () => { button(host, "See the context")?.click(); });
    expect(host.querySelector(".pc-drawer-context")?.textContent).toContain("Alarm FIC-101 PV HI since 10:02");
    await act(async () => { button(host, "Why is it active?")?.click(); });
    const start = calls.find((item) => item.method === "POST" && item.url.endsWith("/api/assistant/chats"));
    expect(start?.body).toEqual({ text: "Why is it active?", ref: "asset:FIC-101", place: "Alarms › FIC-101", keep: true,
      context: "The person chose: Why is it active?\nWhat to do: Read the alarm's signal and say why it is active.\n\nLimit 80, value 92\n\nAlarm FIC-101 PV HI since 10:02" });
    await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
    expect(host.querySelector(".pc-drawer-markdown")?.innerHTML).toContain("<strong>valve</strong>");
    expect(host.textContent).toContain("1 reads of the plant");
    // Every chat is kept (round 8): Full page opens it in Desk's Assistant.
    expect(host.querySelector(".pc-drawer-keep[href]")?.getAttribute("href")).toBe("/assistant/7");
    expect(calls.some((item) => item.url.endsWith("/keep"))).toBe(false);
    // "Your chats" goes back to the start: the earlier chats and the page's tasks. The panel's
    // header is the same as every quick panel's (title, Full page, close): no button of its own.
    expect(button(host.querySelector(".pc-drawer-head")!, "New chat")).toBeUndefined();
    await act(async () => { button(host, "Your chats")?.click(); });
    await act(async () => { await Promise.resolve(); });
    expect(host.querySelector(".pc-drawer-intro h3")?.textContent).toBe("What do you want to do?");
    // The same button closes it.
    await act(async () => { button(host, "Ask the assistant about this page")?.click(); });
    // It folds back to the left (round 8): no longer a dialog, then gone.
    expect(host.querySelector(".pc-drawer[role=dialog]")).toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(PANEL_OUT_MS + 10); });
    expect(host.querySelector(".pc-drawer")).toBeNull();
    expect(calls.some((item) => item.method === "DELETE")).toBe(false); // kept: never deleted on close
    act(() => root.unmount());
  });

  it("counts a demo visit's questions down and stops at none", async () => {
    const answer = { message_id: 2, role: "assistant", text: "Done.", state: "done", steps: [], charts: [], meta: {} };
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const json = (value: unknown) => new Response(JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url.endsWith("/api/assistant")) return json({ available: true, allowed: true, reason: "", chats: [], visit: { questions: 10, max_text: 1200, left: 1 } });
      if (url.endsWith("/api/assistant/chats") && init?.method === "POST") return json({ chat: { chat_id: 7 }, messages: [{ message_id: 1, role: "user", text: "Why?", state: "done", steps: [], charts: [], meta: {} }, answer] });
      return json({ messages: [answer] });
    }));
    const page = () => ({ place: "Desk" });
    const { host, root } = await mount(createElement("div", null, createElement(AssistantTopButton, { platformUrl: "/", page }), createElement(AssistantHost, { platformUrl: "/", page })));
    await act(async () => { button(host, "Ask the assistant about this page")?.click(); });
    await act(async () => { await Promise.resolve(); });
    expect(host.querySelector(".pc-drawer-composer")?.textContent).toContain("1 of 10 questions left in this demo visit.");
    expect((host.querySelector("textarea") as HTMLTextAreaElement).maxLength).toBe(1200);
    await act(async () => { button(host, "Explain this page")?.click(); });
    await act(async () => { await Promise.resolve(); });
    expect(host.querySelector(".pc-drawer-composer")?.textContent).toContain("This visit used its 10 questions.");
    expect((button(host, "Send") as HTMLButtonElement).disabled).toBe(true);
    act(() => root.unmount());
  });

  it("a task that needs the person's words waits for them", async () => {
    const { calls } = server();
    const tasks: AssistantTask[] = [{ label: "Ask about one execution", instructions: "Read that execution.", ask: "Which execution?" }];
    function Page() { useAssistantPage({ place: "Link › Executions", tasks }); return null; }
    const page = () => ({ place: "Link" });
    const { host, root } = await mount(createElement("div", null, createElement(Page), createElement(AssistantTopButton, { platformUrl: "/", page }), createElement(AssistantHost, { platformUrl: "/", page })));
    await act(async () => { button(host, "Ask the assistant about this page")?.click(); });
    await act(async () => { await Promise.resolve(); });
    await act(async () => { button(host, "Ask about one execution")?.click(); });
    expect(calls.some((item) => item.method === "POST")).toBe(false);
    const box = host.querySelector("textarea") as HTMLTextAreaElement;
    expect(box.placeholder).toBe("Which execution?");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set?.call(box, "#42");
      box.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => { (host.querySelector(".pc-drawer-composer") as HTMLFormElement).requestSubmit(); });
    const body = calls.find((item) => item.url.endsWith("/api/assistant/chats"))?.body as { text: string; context: string };
    expect(body.text).toBe("Ask about one execution: #42");
    expect(body.context).toContain("What to do: Read that execution.");
    act(() => root.unmount());
  });

  it("lists the person's earlier chats like Messages and continues one", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { calls } = server();
    const loops = () => ({ place: "Link › Loops" });
    const { host, root } = await mount(createElement("div", null, createElement(AssistantTopButton, { platformUrl: "/", page: loops }), createElement(AssistantHost, { platformUrl: "/", page: loops })));
    await act(async () => { button(host, "Ask the assistant about this page")?.click(); });
    await act(async () => { await Promise.resolve(); });
    await act(async () => { await Promise.resolve(); });
    const earlier = host.querySelector(".pc-drawer-earlier");
    expect(earlier?.querySelector("strong")?.textContent).toBe("Which loops are worst?");
    expect(earlier?.querySelector("small")?.textContent).toContain("Link › Loops");
    await act(async () => { button(host, "Which loops are worst?")?.click(); });
    expect(calls.some((item) => item.method === "GET" && item.url.endsWith("/api/assistant/chats/7"))).toBe(true);
    expect(host.querySelector(".pc-drawer-markdown")?.innerHTML).toContain("<strong>valve</strong>");
    expect(host.querySelector(".pc-drawer-keep[href]")?.getAttribute("href")).toBe("/assistant/7");
    await act(async () => { button(host, "Close")?.click(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(PANEL_OUT_MS + 10); });
    expect(host.querySelector(".pc-drawer")).toBeNull();
    expect(calls.some((item) => item.method === "DELETE")).toBe(false);
    act(() => root.unmount());
  });

  it("is not offered where language models are forbidden, and says why when none is set up", async () => {
    server(false, false);
    const x = () => ({ place: "x" });
    const hidden = await mount(createElement("div", null, createElement(AssistantTopButton, { platformUrl: "/", page: x }), createElement(AssistantHost, { platformUrl: "/", page: x })));
    expect(button(hidden.host, "Ask the assistant about this page")).toBeUndefined();
    act(() => hidden.root.unmount());
    forgetAssistantStatus();
    server(false, true);
    const { host, root } = await mount(createElement("div", null, createElement(AssistantTopButton, { platformUrl: "/", page: x }), createElement(AssistantHost, { platformUrl: "/", page: x })));
    // Dimmed, saying why; for someone who cannot set it up, the panel says the same.
    const off = button(host, "No language model is set up yet.");
    expect(off?.className).toContain("pcs-quick-off");
    await act(async () => { off?.click(); });
    await act(async () => { await Promise.resolve(); });
    expect(host.querySelector(".pc-drawer-off")?.textContent).toContain("No language model is set up yet.");
    expect(host.querySelector("textarea")).toBeNull();
    act(() => root.unmount());
  });

  it("takes an administrator to Setup when no model is set up", async () => {
    server(false, true, true);
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const x = () => ({ place: "x" });
    const { host, root } = await mount(createElement("div", null, createElement(AssistantTopButton, { platformUrl: "/", page: x, variant: "sidebar" }), createElement(AssistantHost, { platformUrl: "/", page: x })));
    const off = button(host, "Click to set it up.");
    await act(async () => { off?.click(); });
    expect(assign).toHaveBeenCalledWith("/setup/language-model");
    expect(host.querySelector(".pc-drawer")).toBeNull();
    act(() => root.unmount());
  });

  it("reads a page's text as the context, cut", () => {
    const root = document.createElement("main");
    root.textContent = `Loops   ${"x".repeat(50)}`;
    expect(pageContext(root, 20)).toBe("Loops xxxxxxxxxxxxxx…");
    expect(pageContext(null)).toBe("");
  });
});

describe("the assistant's button beside a page's title (round 9)", () => {
  it("shows only where the shell draws the panel, and opens it on the page's tasks", async () => {
    server();
    const tasks: AssistantTask[] = [{ label: "Create a block", instructions: "Help write a block file." }];
    function Page() {
      useAssistantPage({ place: "Link › New block", context: "The new-block page", tasks });
      return createElement(Heading, { title: "New block" });
    }
    const alone = await mount(createElement(Page));
    expect(alone.host.querySelector(".pc-title-assistant")).toBeNull();
    act(() => alone.root.unmount());
    const page = () => ({ place: "Link › Blocks", context: "page text" });
    const { host, root } = await mount(createElement("div", null, createElement(Page), createElement(AssistantHost, { platformUrl: "/", page })));
    await act(async () => { await Promise.resolve(); });
    const mark = host.querySelector<HTMLButtonElement>(".page-heading-title .pc-title-assistant");
    expect(mark).not.toBeNull();
    await act(async () => { mark!.click(); });
    await act(async () => { await Promise.resolve(); });
    expect(host.textContent).toContain("Create a block");
    act(() => root.unmount());
  });

  it("is left out with assistant={false}", () => {
    expect(renderToStaticMarkup(createElement(Heading, { title: "Assistant", assistant: false }))).not.toContain("pc-title-assistant");
  });
});

describe("an object's versions in their own tab (round 9)", () => {
  it("lists every version newest first with what changed, who and when, and marks the current one", () => {
    const html = renderToStaticMarkup(createElement(VersionsTab, {
      about: createElement("p", null, "About it"),
      shown: 2,
      versions: [
        { number: 2, name: "Wider window", description: "Window 30 min", author: "Ana", at: "2026-10-25T12:00:00Z", current: true },
        { number: 1, name: "Link's version", note: "ships with Link 0.4.0" },
      ],
    }));
    expect(html).toContain("About it");
    expect(html.indexOf("Version 2")).toBeLessThan(html.indexOf("Version 1"));
    expect(html).toContain("Window 30 min");
    expect(html).toContain("ships with Link 0.4.0");
    expect(html).toContain("current");
  });
});

