/**
 * Where each thing of Models lives (the app's addresses, under its base path):
 *
 * - `/models`, `/models/new`, `/models/<project>/<class>[/<tab>]`: the models, a new one and one
 *   model's page (its tabs, as Analytics' algorithms: inputs and outputs, diagram, test, used by,
 *   versions, settings);
 * - `/editor/<project>/<class>`: a model's diagram editor, in a window of its own;
 * - `/code/<project>?model=<class>`: the Modelica text of a model or a block library;
 * - `/studies`, `/studies/<id>`, `/studies/<id>/runs/<run>`: the studies, one study's comparison
 *   and one of its simulations;
 * - `/executions`, `/executions/<study>`: the queue, every group of runs and one group;
 * - `/runs/<id>`: one simulation or FMU export;
 * - `/blocks`, `/blocks/<class>[/<tab>]`: the blocks a diagram may use and one block (its tabs:
 *   code, inputs and parameters, used by, versions).
 *
 * Addresses of earlier versions (`/projects`, `/simulations`, `/exports`) lead to their new place.
 */
import type { Run } from "./types";

const part = encodeURIComponent;

/** A model's tabs (owner, 2026-10-27: the tabs Analytics' algorithms have, and Settings);
 * Overview has no segment. Run was a test, so it is Test; the studies that use it are Used by. */
export const MODEL_TABS = ["inputs", "diagram", "test", "used-by", "versions", "settings", "compare"] as const;
export type ModelTab = "overview" | (typeof MODEL_TABS)[number];
/** Tabs of an earlier version of the page, and where they are now. */
const OLD_MODEL_TABS: Record<string, ModelTab> = { run: "test", studies: "used-by" };
export const modelPath = (projectId: string, model: string, tab: ModelTab = "overview") => `/models/${part(projectId)}/${part(model)}${tab === "overview" ? "" : `/${tab}`}`;
export const editorPath = (projectId: string, model: string) => `/editor/${part(projectId)}/${part(model)}`;
/** The tab an address names, Overview when it names none (or one a model does not have). */
export function modelTab(segment: string | undefined): ModelTab {
  if (segment && OLD_MODEL_TABS[segment]) return OLD_MODEL_TABS[segment];
  return (MODEL_TABS as readonly string[]).includes(segment ?? "") ? (segment as ModelTab) : "overview";
}
export const codePath = (projectId: string, model?: string) => `/code/${part(projectId)}${model ? `?model=${part(model)}` : ""}`;
export const runPath = (run: Pick<Run, "id">) => `/runs/${part(run.id)}`;
/** A run opened inside its study (round 9 M9): the study stays the place, not Executions. */
export const studyRunPath = (studyId: string, run: Pick<Run, "id">) => `/studies/${part(studyId)}/runs/${part(run.id)}`;
export const studyPath = (study: { id: string; kind?: string }) => (study.kind === "quick" ? `/executions/${part(study.id)}` : `/studies/${part(study.id)}`);
export const BLOCK_TABS = ["code", "inputs", "used-by", "versions", "compare"] as const;
export type BlockTab = "overview" | (typeof BLOCK_TABS)[number];
export const blockPath = (blockId: string, tab: BlockTab = "overview") => `/blocks/${part(blockId)}${tab === "overview" ? "" : `/${tab}`}`;
export function blockTab(segment: string | undefined): BlockTab {
  return (BLOCK_TABS as readonly string[]).includes(segment ?? "") ? (segment as BlockTab) : "overview";
}

/** The new address of an address of an earlier version, or null when it has none. */
export function movedTo(path: string, search = ""): string | null {
  const [, section, id, sub] = path.split("/");
  if (section === "projects") {
    if (id && sub === "edit") return `/code/${id}${search}`;
    return "/models";
  }
  // New model was a dialog on the models page; it is a page of its own (round 9).
  if (section === "models" && !id && new URLSearchParams(search).get("new") === "1") return "/models/new";
  if (section === "simulations" || section === "exports") return id ? `/runs/${id}` : "/executions";
  return null;
}

/** The new-study page with a model already chosen. */
export function newStudyPath(projectId: string, model: string): string {
  return `/studies/new?${new URLSearchParams({ project: projectId, model }).toString()}`;
}
