// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { forgetAssistantStatus } from "./AssistantDrawer";
import { CHART_MODE_KEY, ChartPopover, chartConfig, chartContext, chartModeOf, chartTitle, closeChartAssistant, openChartAssistant, popoverPlace, useOpenedChart } from "./ChartAssistant";

afterEach(() => { forgetAssistantStatus(); vi.unstubAllGlobals(); window.localStorage.clear(); document.body.innerHTML = ""; });

describe("the assistant on each chart", () => {
  it("is off unless a model answers and PlantCraft (or this browser) turns it on", () => {
    expect(chartModeOf(null)).toBe("off");
    expect(chartModeOf({ available: false, charts: "icon" })).toBe("off");
    expect(chartModeOf({ available: true })).toBe("off");
    expect(chartModeOf({ available: true, charts: "icon" })).toBe("icon");
    expect(chartModeOf({ available: true, charts: "sideways" })).toBe("off");
    window.localStorage.setItem(CHART_MODE_KEY, "off");
    expect(chartModeOf({ available: true, charts: "icon" })).toBe("off");
    window.localStorage.setItem(CHART_MODE_KEY, "icon");
    expect(chartModeOf({ available: true })).toBe("icon");
    expect(chartModeOf({ available: false, charts: "icon" })).toBe("off");
  });

  it("names the chart from what it was given, its title or its lines", () => {
    expect(chartTitle([], {}, "FIC-101 PV")).toBe("FIC-101 PV");
    expect(chartTitle([], { title: { text: "<b>PV and SP</b>" } })).toBe("PV and SP");
    expect(chartTitle([{ name: "PV" }, { name: "SP" }], {})).toBe("PV, SP");
    expect(chartTitle([{ name: "A" }, { name: "B" }, { name: "C" }, { name: "D" }], {})).toBe("A, B, C…");
  });

  it("tells the model what the chart draws, never the whole series", () => {
    const x = Array.from({ length: 1000 }, (_, at) => new Date(Date.UTC(2026, 10, 1, 0, 0, at)).toISOString());
    const y: Array<number | null> = x.map((_, at) => (at === 700 ? 95 : at === 10 ? null : 50 + (at % 7)));
    const text = chartContext([{ name: "FIC-101.PV", x, y }, { name: "SP", x: x.slice(0, 3), y: [52, 52, 52] }, { name: "Mode", x: ["2026-11-01T00:00:00Z"], y: ["AUTO"] }, { name: "Map", type: "heatmap", z: [[1]] }], { yaxis: { title: { text: "m³/h" } } }, "Flow");
    expect(text).toContain("Chart: Flow");
    expect(text).toContain("Axes: x -, y m³/h");
    expect(text).toContain("FIC-101.PV: 999 points from 2026-11-01T00:00:00Z");
    expect(text).toContain("max 95 at 2026-11-01T00:11:40Z");
    expect(text).toContain("1 empty");
    expect(text).toContain("SP: 3 points from 2026-11-01T00:00:00Z to 2026-11-01T00:00:02Z, constant at 52");
    expect(text).toContain("Mode: 1 points, states AUTO");
    expect(text).toContain("Map: a heatmap (values not listed)");
    const points = text.split("\n").find((line) => line.includes("points:"))!;
    expect(points.split(";").length).toBeLessThanOrEqual(28);
    expect(text.length).toBeLessThanOrEqual(3501);
  });

  it("adds its button to the chart's row, or makes it the only one of a chart without the row", () => {
    const open = vi.fn();
    const added = chartConfig({ displaylogo: false, modeBarButtonsToAdd: ["v1hovermode"] }, open);
    expect((added.modeBarButtonsToAdd as unknown[]).length).toBe(2);
    const small = chartConfig({ displayModeBar: false }, open);
    expect(small.displayModeBar).toBeUndefined();
    const only = (small.modeBarButtons as Array<Array<{ name: string; click: () => void }>>)[0]![0]!;
    expect(only.name).toBe("assistant");
    only.click();
    expect(open).toHaveBeenCalled();
  });

  it("sits over the chart's corner inside the screen, and at the bottom on a phone", () => {
    expect(popoverPlace({ top: 100, right: 1200 }, 1280, { x: 0, y: 300 })).toEqual({ position: "absolute", width: "380px", left: "812px", top: "408px" });
    expect(popoverPlace({ top: -50, right: 300 }, 1280, { x: 0, y: 0 }).left).toBe("16px");
    expect(popoverPlace({ top: 100, right: 300 }, 390, { x: 0, y: 0 })).toMatchObject({ position: "fixed", bottom: "16px" });
  });

  it("keeps one popover open for the page", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const seen: Array<string | null> = [];
    function Probe() { seen.push(useOpenedChart()); return null; }
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    await act(async () => { root.render(createElement(Probe)); });
    act(() => openChartAssistant("a"));
    act(() => openChartAssistant("b"));
    expect(seen.at(-1)).toBe("b");
    act(() => closeChartAssistant());
    expect(seen.at(-1)).toBeNull();
    act(() => root.unmount());
  });

  it("asks about the chart with what it draws, not kept, and continues in Desk", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const calls: Array<{ url: string; method: string; body: Record<string, unknown> | null }> = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null });
      const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
      if (url.endsWith("/api/assistant")) return json({ available: true, charts: "icon", reason: "", chats: [] });
      if (url.endsWith("/api/assistant/chats") && method === "POST") return json({ chat: { chat_id: 9 }, messages: [{ message_id: 1, role: "user", text: "Explain this chart", state: "done", steps: [] }, { message_id: 2, role: "assistant", text: "", state: "working", steps: [] }] }, 201);
      if (url.endsWith("/api/assistant/chats/9")) return json({ messages: [{ message_id: 1, role: "user", text: "Explain this chart", state: "done", steps: [] }, { message_id: 2, role: "assistant", text: "The flow **rose** at 10:00.", state: "done", steps: [] }] });
      if (url.endsWith("/keep")) return json({ chat_id: 9, kept: true });
      return json({ detail: "no" }, 404);
    }));
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const anchor = document.createElement("div");
    document.body.append(anchor);
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    const onClose = vi.fn();
    await act(async () => { root.render(createElement(ChartPopover, { anchor, title: "Flow", subject: "asset:FIC-101", describe: () => "Chart: Flow\n- PV: 10 points", platformUrl: "/", onClose })); });
    await act(async () => { await Promise.resolve(); });
    const pick = [...host.querySelectorAll("button")].find((item) => item.textContent === "Explain this chart")!;
    await act(async () => { pick.click(); });
    const started = calls.find((item) => item.method === "POST" && item.url.endsWith("/api/assistant/chats"))!;
    expect(started.body).toMatchObject({ text: "Explain this chart", ref: "asset:FIC-101", keep: false });
    expect(String(started.body!.context)).toContain("Chart: Flow");
    expect(String(started.body!.context)).toContain("What to do: Explain what this chart shows");
    await act(async () => { await vi.advanceTimersByTimeAsync(800); });
    expect(host.textContent).toContain("The flow rose at 10:00.");
    expect(host.textContent).toContain("Not kept");
    const desk = [...host.querySelectorAll("button")].find((item) => item.textContent?.includes("Continue in Desk"))!;
    await act(async () => { desk.click(); await Promise.resolve(); await Promise.resolve(); });
    expect(calls.some((item) => item.url.endsWith("/api/assistant/chats/9/keep") && item.method === "POST")).toBe(true);
    expect(assign).toHaveBeenCalledWith(expect.stringContaining("assistant/9"));
    act(() => root.unmount());
    vi.useRealTimers();
  });
});
