import { configureFolders, createApiClient, jsonBody, query, withImageHrefs, type HelpEntry, type HelpPage, type PromptText } from "@plantcraft/ui";
import { href } from "./nav";
import type { BlockCatalog } from "@plantcraft/ui/blockEditor";
import type { AssetRuns, BlockLibrary, BlockUse, CheckResult, ClassInfo, ComputeOffer, Diagram, FileContent, LibraryClass, LibraryEntry, CatalogBlock, Me, ModelDetail, ModelItem, Project, SimSettings, BlockDiagram, ProjectFile, QueueState, Revision, Run, RunnerState, SeriesAnswer, SignalOption, StatisticRow, Study, StudyPreview, StudySeries, SweepItem, Variable } from "./types";

const client = createApiClient({ app: "modelcraft", href });
export const UNAUTHORIZED_EVENT = client.UNAUTHORIZED_EVENT;
// Folders of the site's models, blocks and studies (round 9, M5): the suite's own, as Link's.
const FOLDER_LISTS: Record<string, string> = { model: "/models", block: "/blocks", study: "/studies" };
configureFolders({ request: client.request, href, listPath: (kind) => FOLDER_LISTS[kind] ?? "/" });
const request = client.request;
const body = jsonBody;
const id = encodeURIComponent;

const path = (value: string) => value.split("/").map(encodeURIComponent).join("/");

export const api = {
  me: () => request<Me>("/api/me"),
  runner: () => request<RunnerState>("/api/runner"),
  /** The environments and sizes the suite's compute workers offer now. */
  computeOffer: () => request<ComputeOffer>("/api/compute/offer"),
  // A block's image comes as an app path (round 9 M2): the browser reaches it through href.
  catalog: () => request<BlockCatalog>("/api/catalog").then((found) => ({ ...found, blocks: withImageHrefs(found.blocks, href) })),
  catalogBlock: (blockId: string) => request<CatalogBlock>(`/api/catalog/${id(blockId)}`).then((found) => withImageHrefs([found], href)[0]),
  setBlockDefaults: (blockId: string, values: Record<string, unknown>, version: { name: string; note: string }, baseUpdatedAt: string | null) =>
    request<CatalogBlock>(`/api/catalog/${id(blockId)}/defaults`, body("PUT", { values, version_name: version.name, version_note: version.note, base_updated_at: baseUpdatedAt })).then((found) => withImageHrefs([found], href)[0]),
  duplicateBlock: (blockId: string, name: string) => request<CatalogBlock>(`/api/catalog/${id(blockId)}/duplicate`, body("POST", { name })),
  setBlockImage: (blockId: string, image: string) => request<CatalogBlock>(`/api/catalog/${id(blockId)}/image`, body("PUT", { image })).then((found) => withImageHrefs([found], href)[0]),
  blockUsedBy: (blockId: string) => request<BlockUse[]>(`/api/catalog/${id(blockId)}/used-by`),
  models: () => request<ModelItem[]>("/api/models"),
  model: (projectId: string, model: string) => request<ModelDetail>(`/api/models/${id(projectId)}/${id(model)}`),
  createModel: (name: string, description: string, group: string) => request<ModelDetail>("/api/models", body("POST", { name, description, group })),
  importModel: (fileName: string, text: string, group = "") => request<ModelDetail>("/api/models/import", body("POST", { file_name: fileName, text, group })),
  saveModel: (projectId: string, model: string, diagram: BlockDiagram, settings: SimSettings, baseUpdatedAt: string | null, version: { name: string; note: string } = { name: "", note: "" }) =>
    request<ModelDetail>(`/api/models/${id(projectId)}/${id(model)}`, body("PUT", { diagram, settings, base_updated_at: baseUpdatedAt, version_name: version.name, version_note: version.note })),
  changeModel: (projectId: string, model: string, change: { name?: string; description?: string; group?: string }) => request<ModelDetail>(`/api/models/${id(projectId)}/${id(model)}`, body("PATCH", change)),
  duplicateModel: (projectId: string, model: string, name: string, group = "") => request<ModelDetail>(`/api/models/${id(projectId)}/${id(model)}/duplicate`, body("POST", { name, group })),
  deleteModel: (projectId: string, model: string) => request<void>(`/api/models/${id(projectId)}/${id(model)}`, { method: "DELETE" }),
  runModel: (projectId: string, model: string, label = "") => request<Run>(`/api/models/${id(projectId)}/${id(model)}/run`, body("POST", { label })),
  projects: () => request<Project[]>("/api/projects"),
  project: (projectId: string) => request<Project & { files: ProjectFile[]; classes: ClassInfo[] }>(`/api/projects/${id(projectId)}`),
  createProject: (name: string, description: string, template: string) => request<Project>("/api/projects", body("POST", { name, description, template })),
  changeProject: (projectId: string, change: { name?: string; description?: string }) => request<Project>(`/api/projects/${id(projectId)}`, body("PATCH", change)),
  deleteProject: (projectId: string) => request<void>(`/api/projects/${id(projectId)}`, { method: "DELETE" }),
  duplicateProject: (projectId: string, name: string) => request<Project>(`/api/projects/${id(projectId)}/duplicate`, body("POST", { name })),
  classes: (projectId: string) => request<ClassInfo[]>(`/api/projects/${id(projectId)}/classes`),
  file: (projectId: string, file: string) => request<FileContent>(`/api/projects/${id(projectId)}/files/${path(file)}`),
  saveFile: (projectId: string, file: string, content: string, baseUpdatedAt: string | null) =>
    request<FileContent>(`/api/projects/${id(projectId)}/files/${path(file)}`, body("PUT", { content, base_updated_at: baseUpdatedAt })),
  createFile: (projectId: string, file: string, content: string) => request<FileContent>(`/api/projects/${id(projectId)}/files`, body("POST", { path: file, content })),
  renameFile: (projectId: string, file: string, to: string) => request<FileContent>(`/api/projects/${id(projectId)}/files/${path(file)}/rename`, body("POST", { path: to })),
  deleteFile: (projectId: string, file: string) => request<void>(`/api/projects/${id(projectId)}/files/${path(file)}`, { method: "DELETE" }),
  revisions: (projectId: string, file: string) => request<Revision[]>(`/api/projects/${id(projectId)}/files/${path(file)}/revisions`),
  revision: (projectId: string, revisionId: number) => request<Revision & { content: string }>(`/api/projects/${id(projectId)}/revisions/${revisionId}`),
  importFiles: (projectId: string, files: Record<string, string>, replace = false) => request<{ saved: string[] }>(`/api/projects/${id(projectId)}/import`, body("POST", { files, replace })),
  exportUrl: (projectId: string) => href(`/api/projects/${id(projectId)}/export`),
  classPrompt: (projectId: string, name: string, question?: string) => request<PromptText>(`/api/prompts/class${query({ project_id: projectId, name, question })}`),
  check: (projectId: string, model: string) => request<CheckResult>(`/api/projects/${id(projectId)}/check`, body("POST", { model })),
  diagram: (projectId: string, model: string) => request<Diagram>(`/api/projects/${id(projectId)}/diagram${query({ model })}`),
  edit: (projectId: string, change: Record<string, unknown>) => request<FileContent>(`/api/projects/${id(projectId)}/edit`, body("POST", change)),
  simulate: (projectId: string, settings: Record<string, unknown>) => request<Run>(`/api/projects/${id(projectId)}/simulate`, body("POST", settings)),
  exportFmu: (projectId: string, settings: Record<string, unknown>) => request<Run>(`/api/projects/${id(projectId)}/fmu`, body("POST", settings)),
  runs: (filter: { project?: string; model?: string; kind?: string; study?: string; status?: string; limit?: string } = {}) => request<Run[]>(`/api/runs${query(filter)}`),
  run: (runId: string) => request<Run>(`/api/runs/${id(runId)}`),
  cancelRun: (runId: string) => request<Run>(`/api/runs/${id(runId)}/cancel`, { method: "POST" }),
  queue: () => request<QueueState>("/api/queue/runs"),
  studies: (filter: { project?: string; model?: string } = {}) => request<Study[]>(`/api/studies${query(filter)}`),
  study: (studyId: string) => request<Study>(`/api/studies/${id(studyId)}`),
  previewStudy: (projectId: string, model: string, sweep: SweepItem[]) => request<StudyPreview>(`/api/projects/${id(projectId)}/studies/preview`, body("POST", { model, sweep })),
  createStudy: (projectId: string, settings: Record<string, unknown>) => request<Study>(`/api/projects/${id(projectId)}/studies`, body("POST", settings)),
  changeStudy: (studyId: string, change: { name: string; description?: string }) => request<Study>(`/api/studies/${id(studyId)}`, body("PATCH", change)),
  cancelStudy: (studyId: string) => request<{ cancelled: number }>(`/api/studies/${id(studyId)}/cancel`, { method: "POST" }),
  deleteStudy: (studyId: string) => request<void>(`/api/studies/${id(studyId)}`, { method: "DELETE" }),
  studySeries: (studyId: string, name: string, runs?: string[], envelope = true) => request<StudySeries>(`/api/studies/${id(studyId)}/series`, body("POST", { name, runs: runs ?? null, envelope, max_points: 800 })),
  /** The indicators of any variable of a study's finished runs, by run (round 9 M10). */
  studyIndicators: (studyId: string, name: string) => request<{ name: string; runs: Record<string, Record<string, number | null>> }>(`/api/studies/${id(studyId)}/indicators`, body("POST", { name })),
  studyStatistics: (studyId: string) => request<StatisticRow[]>(`/api/studies/${id(studyId)}/statistics`),
  studyExportUrl: (studyId: string) => href(`/api/studies/${id(studyId)}/export.zip`),
  blocks: () => request<BlockLibrary[]>("/api/blocks"),
  createLibrary: (name: string, group: string, description: string) => request<BlockLibrary>("/api/blocks", body("POST", { name, group, description })),
  changeLibrary: (libraryId: string, change: { name?: string; group?: string; description?: string }) => request<BlockLibrary>(`/api/blocks/${id(libraryId)}`, body("PATCH", change)),
  labelRun: (runId: string, label: string) => request<Run>(`/api/runs/${id(runId)}`, body("PATCH", { label })),
  deleteRun: (runId: string) => request<void>(`/api/runs/${id(runId)}`, { method: "DELETE" }),
  variables: (runId: string) => request<Variable[]>(`/api/runs/${id(runId)}/variables`),
  /** Versions (round 9 M3, M4): a model or a block as an earlier save had it, used again, compared. */
  modelVersion: (projectId: string, model: string, revisionId: number) => request<ModelDetail>(`/api/models/${id(projectId)}/${id(model)}/versions/${revisionId}`),
  useModelVersion: (projectId: string, model: string, revisionId: number) => request<ModelDetail>(`/api/models/${id(projectId)}/${id(model)}/versions/${revisionId}/use`, { method: "POST" }),
  compareModel: (projectId: string, model: string, revisions: number[], labels: string[]) => request<Run[]>(`/api/models/${id(projectId)}/${id(model)}/compare`, body("POST", { revisions, labels })),
  blockVersion: (blockId: string, revisionId: number) => request<CatalogBlock & { code: string; missing: boolean; saved_by: string; saved_at: string }>(`/api/catalog/${id(blockId)}/versions/${revisionId}`).then((found) => withImageHrefs([found], href)[0]),
  series: (runId: string, names: string[], maxPoints = 2000) => request<SeriesAnswer>(`/api/runs/${id(runId)}/series`, body("POST", { names, max_points: maxPoints })),
  resultsUrl: (runId: string) => href(`/api/runs/${id(runId)}/results.csv`),
  fmuUrl: (runId: string) => href(`/api/runs/${id(runId)}/fmu`),
  runFiles: (runId: string) => request<Record<string, string>>(`/api/runs/${id(runId)}/files`),
  library: (parent = "", q = "") => request<{ parent: string; classes: LibraryEntry[] }>(`/api/library${query({ parent, q })}`),
  libraryNames: (prefix: string) => request<string[]>(`/api/library/names${query({ prefix })}`),
  libraryClass: (name: string) => request<LibraryClass>(`/api/library/class${query({ name })}`),
  signals: (q: string) => request<SignalOption[]>(`/api/signals${query({ q, limit: "30" })}`),
  assetRuns: (assetId: string) => request<AssetRuns>(`/api/asset-runs${query({ asset: assetId })}`),
  help: () => request<HelpEntry[]>("/api/help"),
  helpPage: (pageId: string) => request<HelpPage>(`/api/help/${id(pageId)}`),
};
