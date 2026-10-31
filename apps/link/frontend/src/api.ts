import { configureFolders, createApiClient, jsonBody, withImageHrefs, type PromptText } from "@plantcraft/ui";
import type { Diagram, DiagramCheck } from "@plantcraft/ui/blockEditor";
import { href } from "./nav";
import type { Algorithm, ApcController, ApcList, AlgorithmDocs, AlgorithmVersion, AlgorithmTest, AlgorithmUsage, AssetChoice, AssetLink, AssetRun, AssetTiming, BlockCheck, BlockCode, BlockDetail, BlockFileDoc, Blocks, BlockSaved, BlockTestAnswer, CalibrationAnswer, CheckSpec, ComputeOffer, DefaultsVersion, ComputePlacement, Execution, ExecutionGroup, ExecutionList, GroupSubject, OwnSeries, SubjectHistory, HelpDocEntry, HistoryPoint, Job, LoopConfig, LoopDetail, LoopReference, LoopRow, TuningSuggestion, Me, MethodGroup, MethodSpec, ModelExample, ModelExampleCreated, ModelRow, ModelStarter, Overview, QualityRun, RepeatedAlgorithm, ResultList, ResultQuery, RunRow, Schedule, SchedulePreview, SignalAlgorithm, SignalData, SignalDetail, SignalOption, SignalRow, Status_, SyncResult, UserGroup, Verdict } from "./types";
import { RESULT_FILTERS } from "./types";

const client = createApiClient({ app: "linkcraft", href });
// Folders of the site's blocks, algorithms and schedules (round 9, D14): the suite's own.
configureFolders({ request: client.request, href, listPath: (kind) => (kind === "block" ? "/blocks" : kind === "algorithm" ? "/algorithms" : "/schedules") });
export const UNAUTHORIZED_EVENT = client.UNAUTHORIZED_EVENT;
export const requestJson = client.request;
const request = client.request;
const body = jsonBody;
const id = encodeURIComponent;

export interface SignalQuery { q?: string; status?: string[]; source?: string; check?: string; limit?: number; offset?: number }

function signalQuery(params: SignalQuery): string {
  const found = new URLSearchParams();
  if (params.q) found.set("q", params.q);
  if (params.status?.length) found.set("status", params.status.join(","));
  if (params.source) found.set("source", params.source);
  if (params.check) found.set("check", params.check);
  if (params.limit) found.set("limit", String(params.limit));
  if (params.offset) found.set("offset", String(params.offset));
  return found.toString();
}

export const api = {
  me: () => request<Me>("/api/me"),
  apc: (days = 1) => request<ApcList>(`/api/apc?days=${days}`),
  apcController: (controllerId: string, days = 1) => request<ApcController>(`/api/apc/${id(controllerId)}?days=${days}`),
  meta: () => request<{ app?: { version?: string } }>("/api/meta"),
  assetLink: (assetId: string) => request<AssetLink>(`/api/assets/${id(assetId)}`),
  status: () => request<Status_>("/api/status"),
  runRound: () => request<{ started: boolean }>("/api/round", { method: "POST" }),
  loops: () => request<LoopRow[]>("/api/loops"),
  loop: (loopId: string) => request<LoopDetail>(`/api/loops/${id(loopId)}`),
  syncLoops: () => request<{ status: string; found: number; added: number; updated: number; disabled: number }>("/api/loops/sync", { method: "POST" }),
  createLoop: (payload: Record<string, unknown>) => request<{ loop: LoopConfig }>("/api/loops", body("POST", payload)),
  updateLoop: (loopId: string, payload: Record<string, unknown>) => request<{ loop: LoopConfig }>(`/api/loops/${id(loopId)}`, body("PATCH", payload)),
  deleteLoop: (loopId: string) => request<void>(`/api/loops/${id(loopId)}`, { method: "DELETE" }),
  tuningSuggestion: (loopId: string) => request<TuningSuggestion>(`/api/loops/${id(loopId)}/tuning`),
  recordReference: (loopId: string) => request<LoopReference>(`/api/loops/${id(loopId)}/reference`, { method: "POST" }),
  deleteReference: (loopId: string) => request<void>(`/api/loops/${id(loopId)}/reference`, { method: "DELETE" }),
  signalSearch: (q: string) => request<SignalOption[]>(`/api/signal-search?${new URLSearchParams({ q, limit: "20" })}`),
  loopReportUrl: (loopId: string) => href(`/api/loops/${id(loopId)}/report.pdf`),
  jobs: (loopId?: string) => request<Job[]>(`/api/jobs${loopId ? `?${new URLSearchParams({ loop_id: loopId })}` : ""}`),
  job: (jobId: string) => request<Job>(`/api/jobs/${id(jobId)}`),
  createJob: (payload: Record<string, unknown>) => request<Job>("/api/jobs", body("POST", payload)),
  runBatch: (payload: Record<string, unknown>) => request<{ job_ids: string[]; queued: number }>("/api/jobs/batch", body("POST", payload)),
  cancelJob: (jobId: string) => request<Job>(`/api/jobs/${id(jobId)}/cancel`, { method: "POST" }),
  executions: (filters: { status?: string[]; work?: string[]; scheduleId?: string; limit?: number } = {}) => {
    const query = new URLSearchParams();
    for (const item of filters.status ?? []) query.append("status", item);
    for (const item of filters.work ?? []) query.append("work", item);
    if (filters.scheduleId) query.set("schedule_id", filters.scheduleId);
    query.set("limit", String(filters.limit ?? 500));
    return request<ExecutionList>(`/api/executions?${query}`);
  },
  executionGroups: () => request<{ groups: ExecutionGroup[]; manual: ExecutionGroup }>("/api/executions/groups"),
  executionGroup: (groupId: string) => request<{ group: ExecutionGroup; subjects: GroupSubject[] }>(`/api/executions/groups/${id(groupId)}`),
  subjectHistory: (groupId: string, subject: string, run?: string) => request<SubjectHistory>(`/api/executions/groups/${id(groupId)}/${id(subject)}${run ? `?run=${id(run)}` : ""}`),
  ownSeries: (signals: string[], start?: string) => {
    const query = new URLSearchParams();
    for (const item of signals) query.append("signal", item);
    if (start) query.set("start", start);
    return request<{ series: OwnSeries[] }>(`/api/executions/series?${query}`);
  },
  cancelExecution: (executionId: string) => request<Execution>(`/api/executions/${id(executionId)}/cancel`, { method: "POST" }),
  rerunExecution: (executionId: string) => request<Execution>(`/api/executions/${id(executionId)}/rerun`, { method: "POST" }),
  schedules: () => request<Schedule[]>("/api/schedules"),
  schedule: (scheduleId: string) => request<Schedule>(`/api/schedules/${id(scheduleId)}`),
  previewSchedule: (payload: Record<string, unknown>, scheduleId?: string) => request<SchedulePreview>(`/api/schedules/preview${scheduleId ? `?schedule_id=${id(scheduleId)}` : ""}`, body("POST", payload)),
  replaySchedule: (scheduleId: string, hours: number) => request<{ started: boolean; job_id: string }>(`/api/schedules/${id(scheduleId)}/replay`, body("POST", { hours })),
  createSchedule: (payload: Record<string, unknown>) => request<Schedule>("/api/schedules", body("POST", payload)),
  updateSchedule: (scheduleId: string, payload: Record<string, unknown>) => request<Schedule>(`/api/schedules/${id(scheduleId)}`, body("PATCH", payload)),
  runSchedule: (scheduleId: string) => request<{ started: boolean }>(`/api/schedules/${id(scheduleId)}/run`, { method: "POST" }),
  deleteSchedule: (scheduleId: string) => request<void>(`/api/schedules/${id(scheduleId)}`, { method: "DELETE" }),
  methodGroups: () => request<MethodGroup[]>("/api/method-groups"),
  methods: () => request<MethodSpec[]>("/api/methods"),
  prompt: (kind: "method" | "block" | "algorithm", objectId: string, question?: string) =>
    request<PromptText>(`/api/prompts/${kind}/${id(objectId)}${question ? `?question=${id(question)}` : ""}`),
  methodSource: (methodId: string) => request<{ source: string; filename: string }>(`/api/methods/${id(methodId)}/source`),
  saveMethodDefaults: (methodId: string, parameters: Record<string, unknown>, description: string) => request<{ configured_defaults: Record<string, unknown> }>(`/api/methods/${id(methodId)}/defaults`, body("PUT", { parameters, description })),
  methodDefaultsVersions: (methodId: string) => request<DefaultsVersion[]>(`/api/methods/${id(methodId)}/defaults/versions`),
  deleteMethodDefaultsVersion: (methodId: string, number: number) => request<{ deleted: number }>(`/api/methods/${id(methodId)}/defaults/versions/${number}`, { method: "DELETE" }),
  // A block's image comes as an app path (round 9 M2): the browser reaches it through href.
  blocks: () => request<Blocks>("/api/blocks").then((found) => ({ ...found, blocks: withImageHrefs(found.blocks, href) })),
  block: (blockId: string, version?: number) => request<BlockDetail>(`/api/blocks/${id(blockId)}${version ? `?version=${version}` : ""}`).then((found) => withImageHrefs([found], href)[0]),
  selectBlockVersion: (blockId: string, number: number) => request<BlockSaved>(`/api/blocks/${id(blockId)}/current`, body("POST", { number })),
  blockCode: (blockId: string, version?: number) => request<BlockCode>(`/api/blocks/${id(blockId)}/code${version ? `?version=${version}` : ""}`),
  blockFile: (blockId: string, version?: number) => request<BlockFileDoc>(`/api/blocks/${id(blockId)}/file${version ? `?version=${version}` : ""}`),
  blockCopy: (blockId: string, edit = false, version?: number) => {
    const query = [edit ? "edit=true" : "", version ? `version=${version}` : ""].filter(Boolean).join("&");
    return request<BlockFileDoc>(`/api/blocks/${id(blockId)}/copy${query ? `?${query}` : ""}`);
  },
  createLibrary: (name: string, description: string) => request<{ library: string; name: string; description: string }>("/api/blocks/libraries", body("POST", { name, description })),
  checkBlock: (file: BlockFileDoc | string) => request<BlockCheck>("/api/blocks/check", body("POST", { file })),
  createBlock: (file: BlockFileDoc, versionName = "", versionDescription = "") =>
    request<BlockSaved>("/api/blocks", body("POST", { file, version_name: versionName, version_description: versionDescription })),
  saveBlockVersion: (blockId: string, file: BlockFileDoc, name: string, description: string) =>
    request<BlockSaved>(`/api/blocks/${id(blockId)}/versions`, body("POST", { file, name, description })),
  updateBlock: (blockId: string, payload: { owner?: string; owner_name?: string; tags?: string[] }) => request<unknown>(`/api/blocks/${id(blockId)}`, body("PATCH", payload)),
  deleteBlock: (blockId: string) => request<unknown>(`/api/blocks/${id(blockId)}`, { method: "DELETE" }),
  /** ``end``: the window's end (versions compared run on the same data); now when not given. */
  testBlock: (file: BlockFileDoc | { block_id: string }, assetId: string, roles: Record<string, string>, signals: Record<string, string>, parameters: Record<string, unknown>, end?: string) =>
    request<BlockTestAnswer>("/api/blocks/test", body("POST", { file, asset_id: assetId, roles, signals, parameters, end: end ?? null })),
  blockPeople: () => request<Array<{ username: string; name: string; role?: string | null }>>("/api/blocks/people"),
  newBlockPrompt: (requestText: string) => request<PromptText>(`/api/prompts/new-block?${new URLSearchParams({ request: requestText })}`),
  algorithms: () => request<Algorithm[]>("/api/algorithms"),
  algorithm: (algorithmId: string) => request<Algorithm>(`/api/algorithms/${id(algorithmId)}`),
  repeatedAlgorithms: () => request<RepeatedAlgorithm[]>("/api/algorithms/repeated"),
  removeRepeated: (algorithmIds: string[]) => request<{ removed: string[] }>("/api/algorithms/repeated/remove", body("POST", { algorithm_ids: algorithmIds })),
  algorithmVersions: (algorithmId: string) => request<AlgorithmVersion[]>(`/api/algorithms/${id(algorithmId)}/versions`),
  algorithmVersion: (algorithmId: string, version: number) => request<Algorithm>(`/api/algorithms/${id(algorithmId)}/versions/${version}`),
  /** The algorithm as the assistant reads it, in Markdown. */
  algorithmText: (algorithmId: string) => request<{ ref: string; markdown: string }>(`/api/algorithms/${id(algorithmId)}/markdown`),
  checkAlgorithm: (diagram: Diagram) => request<DiagramCheck>("/api/algorithms/check", body("POST", { diagram })),
  /** The documentation the diagram gives, for the fields left empty. */
  generatedDocs: (diagram: Diagram, name: string, description: string) => request<AlgorithmDocs>("/api/algorithms/docs", body("POST", { diagram, name, description })),
  /** A test on one loop's recent data, or over ``window`` (a past run's, run again). */
  testAlgorithm: (diagram: Diagram, loopId?: string, window?: { start: string; end: string }) =>
    request<AlgorithmTest>("/api/algorithms/test", body("POST", { diagram, loop_id: loopId || null, start: window?.start ?? null, end: window?.end ?? null })),
  /** A test of an algorithm on assets: one run on the asset, its window ending at ``end`` (now). */
  testOnAsset: (diagram: Diagram, assetId: string, timing: AssetTiming, end?: string) =>
    request<AlgorithmTest>("/api/algorithms/test", body("POST", { diagram, asset_id: assetId, timing, end: end || null })),
  models: () => request<ModelRow[]>("/api/models"),
  modelStarter: (modelId: string) => request<ModelStarter>(`/api/models/${id(modelId)}/starter`),
  /** The Simulator demo plant's model algorithms (Furnaces, FIC-1001, LIC-1010) this plant can have. */
  modelExamples: () => request<ModelExample[]>("/api/models/examples"),
  createModelExamples: () => request<ModelExampleCreated[]>("/api/models/examples", { method: "POST" }),
  calibrate: (diagram: Diagram, nodeId: string, assetId: string, timing: AssetTiming, start: string, end: string) =>
    request<CalibrationAnswer>("/api/algorithms/calibrate", body("POST", { diagram, node_id: nodeId, asset_id: assetId, timing, start, end })),
  saveAlgorithm: (algorithm: { algorithm_id: string; name: string; description: string; subject_kind: string; diagram: Diagram; docs: AlgorithmDocs; timing?: AssetTiming; assets?: string[]; compute?: ComputePlacement; tags?: string[]; version_name?: string; version_note?: string }) =>
    request<Algorithm>(`/api/algorithms/${id(algorithm.algorithm_id)}`, body("PUT", algorithm)),
  /** Who answers for an algorithm, its tags and its responsible group ("" frees it); not a new version. */
  updateAlgorithm: (algorithmId: string, payload: { owner?: string; owner_name?: string; tags?: string[]; group_id?: string }) =>
    request<Algorithm>(`/api/algorithms/${id(algorithmId)}`, body("PATCH", payload)),
  /** The environments and sizes the suite's compute workers offer now. */
  computeOffer: () => request<ComputeOffer>("/api/compute/offer"),
  userGroups: () => request<UserGroup[]>("/api/user-groups"),
  deleteAlgorithm: (algorithmId: string) => request<void>(`/api/algorithms/${id(algorithmId)}`, { method: "DELETE" }),
  helpDocs: () => request<HelpDocEntry[]>("/api/help/docs"),
  helpDoc: (docId: string) => request<{ id: string; title: string; markdown: string }>(`/api/help/docs/${docId.split("/").map(id).join("/")}`),
  overview: () => request<Overview>("/api/overview"),
  // `kind` (signal, loop or asset row) is for the Overview's counts; the page filters by asset type.
  results: (params: ResultQuery & { kind?: string[]; limit?: number }) => request<ResultList>(`/api/results?${resultParams(params, { limit: String(params.limit ?? 200), ...(params.kind?.length ? { kind: params.kind.join(",") } : {}) })}`),
  /** The PDF of the results a filter keeps (the weekly report of 0.3, for any filter). */
  resultsReportUrl: (params: ResultQuery) => href(`/api/reports/results.pdf?${resultParams(params)}`),
  /** Writes what Link knows about an algorithm or a run to PlantCraft, for the assistant. */
  prepareAssistant: (ref: string) => request<{ ref: string; published: boolean }>("/api/assistant/prepare", body("POST", { ref })),
  signals: (params: SignalQuery = {}) => request<{ total: number; items: SignalRow[] }>(`/api/signals?${signalQuery(params)}`),
  signal: (signalId: string) => request<SignalDetail>(`/api/signals/${id(signalId)}`),
  signalData: (signalId: string, start?: string, end?: string) => request<SignalData>(`/api/signals/${id(signalId)}/data${start || end ? `?${new URLSearchParams({ ...(start ? { start } : {}), ...(end ? { end } : {}) })}` : ""}`),
  signalHistory: (signalId: string, days = 30) => request<HistoryPoint[]>(`/api/signals/${id(signalId)}/history?days=${days}`),
  checkSignal: (signalId: string, window: { start?: string; end?: string } = {}) => request<Verdict>(`/api/signals/${id(signalId)}/check`, body("POST", window)),
  updateSignal: (signalId: string, payload: Record<string, unknown>) => request<SignalDetail>(`/api/signals/${id(signalId)}`, body("PATCH", payload)),
  syncSignals: () => request<SyncResult>("/api/signals/sync", { method: "POST" }),
  signalAlgorithm: () => request<SignalAlgorithm>("/api/signal-quality"),
  saveSignalAlgorithm: (payload: Record<string, unknown>) => request<SignalAlgorithm>("/api/signal-quality", body("PUT", payload)),
  runSignalQuality: () => request<{ started: boolean }>("/api/signal-quality/run", { method: "POST" }),
  qualityRuns: (limit = 50) => request<QualityRun[]>(`/api/signal-quality/runs?limit=${limit}`),
  /** Every algorithm's runs on one history, newest first. */
  runs: (limit = 500) => request<{ total: number; items: RunRow[] }>(`/api/runs?limit=${limit}`),
  /** Where an algorithm is used: its schedules and the subjects it works on. */
  algorithmUsage: (algorithmId: string) => request<AlgorithmUsage>(`/api/algorithms/${id(algorithmId)}/usage`),
  /** The latest run of an algorithm on assets on each of its assets. */
  algorithmRuns: (algorithmId: string) => request<AssetRun[]>(`/api/algorithms/${id(algorithmId)}/runs`),
  runAlgorithm: (algorithmId: string) => request<AssetRun[]>(`/api/algorithms/${id(algorithmId)}/run`, { method: "POST" }),
  /** Every asset of PlantCraft, for an algorithm on assets to name. */
  assetChoices: () => request<AssetChoice[]>("/api/asset-choices"),
  qualityRun: (runId: string | number) => request<QualityRun>(`/api/signal-quality/runs/${id(String(runId))}`),
};

let catalog: Promise<CheckSpec[]> | null = null;
/** The Data quality checks with this site's settings, read once per page load (names, filters, toggles). */
export function checkCatalog(refresh = false): Promise<CheckSpec[]> {
  if (refresh || !catalog) catalog = api.signalAlgorithm().then((algorithm) => algorithm.checks).catch((error: unknown) => { catalog = null; throw error; });
  return catalog;
}

/** A Results filter as query parameters: each list joined with commas, empty ones left out. */
export function resultParams(params: ResultQuery, extra: Record<string, string> = {}): string {
  const query = new URLSearchParams(extra);
  for (const key of ["status", ...RESULT_FILTERS] as const) if (params[key]?.length) query.set(key, params[key]!.join(","));
  if (params.q) query.set("q", params.q);
  return query.toString();
}
