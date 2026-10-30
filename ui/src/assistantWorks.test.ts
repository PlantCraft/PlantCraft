// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Heading } from "./Blocks";
import { AssistantHost, closeAssistant, createdId, fieldInput, fieldValues, forgetAssistantStatus, missingFields, ProposalCard, takeAssistantDraft, useAssistantPage, workRoute, type AssistantWorkField } from "./AssistantDrawer";

type Call = { url: string; method: string; body: unknown };

const FIELDS: AssistantWorkField[] = [
  { key: "title", title: "Title", type: "text", required: true },
  { key: "priority", title: "Priority", type: "choice", options: ["low", "normal", "high"] },
  { key: "due_at", title: "Due", type: "datetime" },
  { key: "tags", title: "Tags", type: "list" },
  { key: "hours", title: "Hours", type: "number" },
];
const NEW_ACTION = { key: "processcraft:new-action", app: "processcraft", kind: "create", title: "Create an action", hint: "The assistant asks what it needs", object: "action", fields: FIELDS, create: "/api/actions", open: "/actions/{id}" };
const ABOUT = { key: "processcraft:about-actions", app: "processcraft", kind: "ask", title: "Ask about these actions" };

function server() {
  const calls: Call[] = [];
  const proposal = { work: NEW_ACTION.key, object: "action", fields: { title: "Check FV-101", priority: "high" }, state: "proposed",
    card: { app: "processcraft", title: "Create an action", fields: FIELDS, create: "/api/actions", open: "/actions/{id}" } };
  const answer = { message_id: 2, role: "assistant", text: "", state: "working", steps: [], charts: [], meta: {} };
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null });
    const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
    if (url.endsWith("/api/assistant")) return json({ available: true, allowed: true, reason: "", chats: [] });
    if (url.includes("/api/assistant/works?")) return json({ page: "processcraft:actions", works: [NEW_ACTION, ABOUT] });
    if (url.endsWith("/api/assistant/chats") && method === "POST") return json({ chat: { chat_id: 9 }, messages: [{ message_id: 1, role: "user", text: "Create an action", state: "done", steps: [], charts: [], meta: {} }, answer] }, 201);
    if (url.endsWith("/api/assistant/chats/9") && method === "GET") return json({ messages: [{ ...answer, state: "done", text: "Here is the action.", meta: { proposals: [proposal] } }] });
    if (url.endsWith("/api/actions") && method === "POST") return json({ action_id: 41, title: "Check FV-101 stiction" }, 201);
    if (url.endsWith("/api/assistant/chats/9/proposals")) return json({ proposal: { state: "created" } });
    return json({ detail: "no" }, 404);
  }));
  return calls;
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
const settle = async () => { for (let n = 0; n < 4; n += 1) await act(async () => { await Promise.resolve(); }); };

afterEach(() => { act(() => closeAssistant()); forgetAssistantStatus(); vi.useRealTimers(); vi.unstubAllGlobals(); document.body.innerHTML = ""; });

describe("the assistant's works", () => {
  it("lists the page's works beside the title, starts the chosen one, and creates from the card", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const calls = server();
    function Page() {
      useAssistantPage({ place: "Desk › Actions", page: "processcraft:actions", facts: { open: 3 }, view: { filters: { mine: true } } });
      return createElement(Heading, { title: "Actions" });
    }
    const { host, root } = await mount(createElement("div", null, createElement(Page), createElement(AssistantHost, { platformUrl: "/", page: () => ({ place: "Actions" }) })));
    await settle();
    await act(async () => { host.querySelector<HTMLButtonElement>(".pc-title-assistant")!.click(); });
    await settle();
    const menu = host.querySelector(".pc-title-assistant-menu");
    expect([...menu!.querySelectorAll("strong")].map((item) => item.textContent)).toEqual([
      "Create an actionCreates", "Ask about these actions", "Explain this page",
    ]);
    expect(calls.some((item) => item.url === "/api/assistant/works?page=processcraft%3Aactions")).toBe(true);
    await act(async () => { button(menu!, "Create an action")!.click(); });
    await settle();
    expect(host.querySelector(".pc-title-assistant-menu")).toBeNull();
    const start = calls.find((item) => item.method === "POST" && item.url.endsWith("/api/assistant/chats"));
    expect(start?.body).toMatchObject({ text: "Create an action", work: "processcraft:new-action", place: "Desk › Actions",
      page: { page: "processcraft:actions", subject: "", facts: { open: 3 }, view: { filters: { mine: true } } } });
    await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
    await settle();
    const card = host.querySelector<HTMLFormElement>(".pc-proposal");
    expect(card).not.toBeNull();
    const title = card!.querySelector<HTMLInputElement>("#pc-proposal-title")!;
    expect(title.value).toBe("Check FV-101");
    expect(card!.querySelector<HTMLSelectElement>("#pc-proposal-priority")!.value).toBe("high");
    // The person changes a field before creating.
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
      setter.call(title, "Check FV-101 stiction");
      title.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const seen: unknown[] = [];
    window.addEventListener("pc-assistant-created", (event) => seen.push((event as CustomEvent).detail));
    await act(async () => { button(card!, "Create action")!.click(); });
    await settle();
    const created = calls.find((item) => item.method === "POST" && item.url === "/api/actions");
    expect(created?.body).toEqual({ title: "Check FV-101 stiction", priority: "high" });
    const recorded = calls.find((item) => item.url.endsWith("/api/assistant/chats/9/proposals"));
    expect(recorded?.body).toEqual({ message_id: 2, index: 0, state: "created", ref: "action:41", href: "/actions/41" });
    expect(host.querySelector(".pc-proposal-done")?.textContent).toContain("Created: Check FV-101 stiction");
    expect(host.querySelector(".pc-proposal-done a")?.getAttribute("href")).toBe("/actions/41");
    expect(seen).toEqual([{ work: "processcraft:new-action", object: "action", id: "41" }]);
    act(() => root.unmount());
  });

  it("turns the card's inputs into what the create route takes", () => {
    const inputs = { title: " Check ", priority: "", due_at: "2026-10-27T09:00", tags: "a, b,", hours: "1.5" };
    const body = fieldValues(FIELDS, inputs);
    expect(body).toMatchObject({ title: "Check", tags: ["a", "b"], hours: 1.5 });
    expect(body).not.toHaveProperty("priority");
    expect(new Date(String(body.due_at)).getTime()).toBe(new Date("2026-10-27T09:00").getTime());
    expect(fieldInput(FIELDS[2], body.due_at)).toBe("2026-10-27T09:00");
    expect(fieldInput(FIELDS[3], ["a", "b"])).toBe("a, b");
    expect(missingFields(FIELDS, { title: " " })).toEqual(["Title"]);
    expect(createdId("action", { action_id: 41 })).toBe("41");
    expect(createdId("block", { block: { id: "pid-check" } })).toBe("pid-check");
    expect(createdId("block", { ok: true })).toBe("");
    expect(workRoute("/", "processcraft", "/api/actions")).toBe("/api/actions");
    expect(workRoute("https://plant.example/", "linkcraft", "/link/api/blocks")).toBe("/link/api/blocks");
  });
});

describe("a create work that continues in the object's own form", () => {
  it("hands the card's fields to the form, which reads them once", async () => {
    const calls: Call[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method ?? "GET", body: init?.body ? JSON.parse(String(init.body)) : null });
      return new Response(JSON.stringify({ proposal: { state: "opened" } }), { status: 200, headers: { "Content-Type": "application/json" } });
    }));
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const fields: AssistantWorkField[] = [{ key: "name", title: "Name", type: "text", required: true }, { key: "inputs", title: "Inputs", type: "list" }];
    const proposal = { work: "linkcraft:new-block", object: "block", fields: { name: "Drift", inputs: ["pv"] }, state: "proposed" as const,
      card: { app: "linkcraft", title: "Write a block", fields, form: "/link/blocks/new" } };
    const { host, root } = await mount(createElement(ProposalCard, { base: "/", chatId: 9, messageId: 2, index: 0, proposal }));
    await act(async () => { button(host, "Continue in the block form")!.click(); });
    await settle();
    expect(assign).toHaveBeenCalledWith("/link/blocks/new");
    expect(calls[0]).toMatchObject({ url: "/api/assistant/chats/9/proposals", body: { state: "opened", href: "/link/blocks/new" } });
    expect(host.querySelector(".pc-proposal-done")?.textContent).toContain("Opened in its form: Drift");
    expect(takeAssistantDraft("linkcraft:new-block")).toEqual({ name: "Drift", inputs: ["pv"] });
    expect(takeAssistantDraft("linkcraft:new-block")).toBeNull();
    // Its Open hands them over again: the form read the first draft already.
    const open = host.querySelector<HTMLAnchorElement>(".pc-proposal-done a")!;
    open.addEventListener("click", (event) => event.preventDefault());
    act(() => open.click());
    expect(takeAssistantDraft("linkcraft:new-block")).toEqual({ name: "Drift", inputs: ["pv"] });
    act(() => root.unmount());
  });
});
