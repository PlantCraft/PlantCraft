/**
 * Which chart the assistant is about: the chart the person last pointed at (the "focus" trial)
 * and the chart whose popover is open. Kept apart from the popover (ChartAssistant.tsx) so the
 * menu beside the page's title (AssistantDrawer.tsx) can offer the focused chart without the two
 * importing each other.
 */
import { useSyncExternalStore } from "react";

/** How the assistant is offered on charts (`PLANTCRAFT_ASSISTANT_CHARTS`, a trial, 2026-11-02):
 * "icon" puts its mark in each chart's buttons, "focus" adds the chart last pointed at to the
 * menu beside the page's title. Both open the same popover over the chart. */
export type ChartAssistantMode = "off" | "icon" | "focus";

const MODES: ChartAssistantMode[] = ["off", "icon", "focus"];
/** A person trying the other way in their own browser: `localStorage["pc-assistant-charts"]`. */
export const CHART_MODE_KEY = "pc-assistant-charts";

/** The mode PlantCraft sets (`charts` in `GET /api/assistant`), or the one this browser tries. */
export function chartModeOf(status: { available?: boolean; charts?: string } | null | undefined): ChartAssistantMode {
  if (!status?.available) return "off";
  let tried: string | null = null;
  try { tried = window.localStorage.getItem(CHART_MODE_KEY); } catch { tried = null; }
  const value = (tried ?? status.charts ?? "off") as ChartAssistantMode;
  return MODES.includes(value) ? value : "off";
}

/** A chart the assistant can be asked about. */
export type ChartEntry = { id: string; title: string };

let focused: ChartEntry | null = null;
let opened: string | null = null;
// The question the popover asks at once (picked in the menu beside the title), read once.
let asked: number | null = null;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((listener) => listener());
const subscribe = (listener: () => void) => { listeners.add(listener); return () => listeners.delete(listener); };

/** The person pointed at this chart (or moved into it with the keyboard). */
export function focusChart(entry: ChartEntry) {
  if (focused?.id === entry.id && focused.title === entry.title) return;
  focused = entry; emit();
}
/** The chart left the page. */
export function forgetChart(id: string) {
  let changed = false;
  if (focused?.id === id) { focused = null; changed = true; }
  if (opened === id) { opened = null; changed = true; }
  if (changed) emit();
}
/** Open the assistant's popover over this chart (closing any other); with `question`, the
 * index of one of its questions (`chartQuestions()`), asked at once. */
export function openChartAssistant(id: string, question: number | null = null) { opened = id; asked = question; emit(); }
/** The question to ask at once, read once by the popover that opens. */
export function takeChartQuestion(): number | null { const value = asked; asked = null; return value; }
export function closeChartAssistant() { if (opened === null) return; opened = null; emit(); }

export function useFocusedChart(): ChartEntry | null { return useSyncExternalStore(subscribe, () => focused, () => null); }
export function useOpenedChart(): string | null { return useSyncExternalStore(subscribe, () => opened, () => null); }
