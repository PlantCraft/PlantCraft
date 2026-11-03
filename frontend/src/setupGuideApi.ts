/** The setup guide (/api/setup-guide, plantcraft/setup_guide.py): the steps of a new
 * installation, each with its state and the facts the robot reads. */
import { requestJson } from "./api";

export type GuideStepState = "done" | "skipped" | "current" | "todo";
export type GuideSource = { source_id: string; name: string; type: string; endpoint: string | null; enabled: boolean; signals: number; state: { status?: string; detail?: string } | null };
export type GuideStep = {
  id: string;
  title: string;
  summary: string;
  why: string;
  page: string;
  page_label: string;
  optional: boolean;
  /** The guide sees by itself when it is done; false: the person says so. */
  seen: boolean;
  state: GuideStepState;
  marked: "done" | "skipped" | null;
  facts: Record<string, unknown>;
  /** The assistant's work for this step (`processcraft:guide-<id>`). */
  work: string;
  sources?: GuideSource[];
};
export type Guide = { hidden: boolean; ready: boolean; current: string | null; done: number; total: number; finished: boolean; steps: GuideStep[] };
export type ConnectionTest = { ok: boolean; message: string };
export type StartStep = { app: string; app_name: string; id: string; title: string; description: string; open?: string | null };

export const guideApi = {
  get: () => requestJson<Guide>("/api/setup-guide"),
  mark: (step: string, state: "done" | "skipped" | null) => requestJson<Guide>(`/api/setup-guide/steps/${encodeURIComponent(step)}`, { method: "POST", body: JSON.stringify({ state }) }),
  hide: (hidden: boolean) => requestJson<Guide>("/api/setup-guide/hide", { method: "POST", body: JSON.stringify({ hidden }) }),
  test: (source: string) => requestJson<{ test: ConnectionTest; guide: Guide }>(`/api/setup-guide/connection/${encodeURIComponent(source)}/test`, { method: "POST" }),
  startSteps: () => requestJson<{ steps: StartStep[] }>("/api/asset-file/start"),
  takeStart: (step: StartStep) => requestJson<{ summary: string; open?: string | null }>(`/api/asset-file/start/${encodeURIComponent(step.app)}/${encodeURIComponent(step.id)}`, { method: "POST" }),
};

/** The event any page sends to open the guide (Settings › Setup guide, the user menu). */
export const OPEN_GUIDE_EVENT = "plantcraft:setup-guide";
export function openSetupGuide() { window.dispatchEvent(new CustomEvent(OPEN_GUIDE_EVENT)); }

/** What the robot says in its bubble about the step that comes now. */
export function guideLine(guide: Guide): string {
  const step = guide.steps.find((item) => item.id === guide.current);
  return step ? step.summary : "";
}

/** The facts the step's work reads: where the person is in the guide and the step's own state. */
export function stepFacts(guide: Guide, step: GuideStep): Record<string, unknown> {
  return {
    step: step.id,
    step_title: step.title,
    step_page: `${step.page_label} (${step.page})`,
    steps: guide.steps.map((item) => `${item.title}: ${item.state}`).join("; "),
    ...step.facts,
  };
}
