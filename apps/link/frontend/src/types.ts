import type { BlockCatalog, Diagram, DiagramCheck, DiagramTrace, TraceValue } from "@plantcraft/ui/blockEditor";
export type Status = "critical" | "high" | "medium" | "normal" | "inactive" | "no_data" | "pending" | string;

export interface Me {
  username: string; name: string; level: string; access: string; role: string; can_edit: boolean; is_admin: boolean;
  processcraft_url: string; version: string;
  /** A public demo visit (read-only: every change is refused, also the editors' reads). */
  demo?: { ends: number } | null;
}

export interface Finding { method_id: string; value?: number | null; severity?: string; finding?: string }

export interface LoopRow {
  loop_id: string; name: string; area: string; service: string; unit: string; profile_id: string;
  criticality: string; status: Status; state?: string | null; state_reason?: string | null;
  health?: number | null; worst_method: string; worst_score?: number | null; limiting?: Finding | null;
  context: Finding[]; alerts: Finding[]; coverage: number; priority: number; origin: string; analyzed_at?: string | null;
  loop_type?: string | null; missing_roles?: string[];
}

export interface MethodResult {
  method_id: string; status: string; score?: number | null; severity?: string; message?: string; finding?: string;
  metrics?: Record<string, unknown>; limitations?: string[];
}

export interface LoopSignals { pv?: string | null; sp?: string | null; op?: string | null; mode?: string | null; secondary?: string | null }

/** What PlantCraft's asset record says about a loop (owned by PlantCraft). */
export interface AssetRecord {
  type_id: string; type_path: string[]; loop_type?: string | null; criticality?: string | null;
  action?: string | null; controller?: string | null; relations: Array<{ type: string; to: string }>;
  required_roles: string[]; missing_roles: string[]; roles_source: string;
}

export interface LoopConfig {
  loop_id: string; name: string; area: string; service: string; unit: string; enabled: boolean;
  signals: LoopSignals; profile_id: string; method_parameters: Record<string, Record<string, unknown>>;
  metadata: Record<string, unknown>; asset_record?: AssetRecord | null; set_here?: string[];
}

/** Where a CPM setting comes from: PlantCraft's asset record, a person here, or LinkCraft's default. */
export type SettingSource = "asset" | "here" | "default";

export interface LoopSummary {
  status?: Status; health?: number | null; limiting?: Finding | null; alerts?: Finding[]; context?: Finding[];
  operating_state?: string; operating_state_reason?: string; valid_fraction?: number; sample_count?: number;
  data_quality?: { apt?: boolean; reasons?: string[] }; functional_components?: Finding[];
  current_pv?: number | null; current_sp?: number | null; current_op?: number | null;
  /** The algorithm's blocks as they ran (each one's verdict), and its outputs. */
  blocks?: Record<string, BlockResult>; outputs?: AlgorithmOutput[];
}

export interface SeriesPoint { timestamp: string; pv?: number | null; sp?: number | null; op?: number | null; mode?: string | number | null }

export interface LoopDetail {
  loop: LoopConfig; origin: string; summary: LoopSummary | null; results: MethodResult[]; likely_causes?: LikelyCause[];
  /** What LinkCraft publishes to PlantCraft for this loop: ok, warning, alarm or unknown. */
  suite_status?: string;
  incomplete?: boolean; missing_roles?: string[]; loop_type_known?: boolean;
  settings_source?: Record<"profile_id" | "criticality" | "method_parameters", SettingSource>;
  record_defaults?: { profile_id: string; criticality: string } | null;
  source_start?: string | null; source_end?: string | null; analyzed_at?: string | null;
  series: SeriesPoint[]; history: Array<{ source_end: string; status: string; health: number | null }>; jobs: Job[];
  /** The last run against the run someone recorded as the loop's reference (A8); null without one. */
  reference?: LoopReference | null;
}

export interface ReferenceIndicator { reference: number; now: number; index: number | null }

export interface LoopReference {
  recorded_at: string; recorded_by: string; source_start?: string | null; source_end?: string | null;
  health_reference: number | null; health_now: number | null; health_change: number | null; version_changed: boolean;
  methods: Array<{ method_id: string; status_reference: string; status_now: string; score_reference: number | null; score_now: number | null; score_change: number | null; indicators: Record<string, ReferenceIndicator> }>;
}

export interface Job {
  job_id: string; loop_id: string; schedule_id?: string | null; name: string; kind: string; status: string;
  status_label?: string; requested_at: string; started_at?: string | null; completed_at?: string | null;
  source_start?: string | null; source_end?: string | null; lookback_minutes?: number | null; profile_id?: string | null;
  summary?: LoopSummary; results?: MethodResult[]; error_message?: string | null; created_by?: string;
}

export interface Selector { mode: "all" | "list" | "filter"; ids?: string[]; areas?: string[]; statuses?: string[]; q?: string }

export interface Schedule {
  schedule_id: string; name: string; loop_id: string; cadence: string; enabled: number | boolean; kind?: "round" | "cycle" | "protocol" | "algorithm";
  next_run_at?: string | null; last_run_at?: string | null; last_run_by_hand?: boolean; lookback_minutes: number; profile_id?: string | null;
  interval_minutes?: number | null; time_local?: string | null; weekday?: number | null; timezone?: string; scheduled_for?: string | null;
  selector?: Selector | null; subject_label?: string; created_by?: string; owner?: string | null;
  priority?: number; spread_minutes?: number; last_summary?: { jobs?: number; skipped?: number } & Record<string, unknown>;
  work?: "loop" | "round" | "asset"; algorithm?: { id: string; name: string } | null;
  editable?: { subjects: boolean; timing: boolean; algorithm: boolean; delete: boolean };
  subject_count?: number; subjects?: string[]; subject_kind?: "loop" | "asset";
  recurrence?: Recurrence | null; retry?: RetryPolicy; when?: string; stats?: ScheduleStats;
  output_key?: string | null; outputs?: Record<string, OutputChoice>; recorded_outputs?: RecordedOutput[];
  /** An algorithm on assets: the monitor's own parameter values, on top of the algorithm's. */
  method_config?: { node_parameters?: NodeParameters } & Record<string, unknown>;
}

/** `{node id: {parameter: value}}`: values a monitor sets on its algorithm's blocks. */
export type NodeParameters = Record<string, Record<string, unknown>>;

/** How long a recorded output is kept: forever, for days, or (a series) its last executions. */
export type OutputKeep = { forever?: boolean; days?: number; runs?: number };
/** A schedule's choice for one recorded output. */
export type OutputChoice = { record: boolean; keep?: OutputKeep };
/** One port an asset schedule records (``linkcraft.assets.outputs``), with its cost per asset. */
export type RecordedOutput = {
  key: string; name: string; kind: "number" | "verdict" | "series"; unit: string; description: string; values_per_run: number;
  record: boolean; keep: OutputKeep; values_per_day: number; stored_values: number; stored_bytes: number; grows: boolean;
};

/** A schedule's calendar (``linkcraft.engine.recurrence``); weekdays are 0 (Monday) to 6. */
export type Recurrence = {
  freq: "minutes" | "hours" | "days" | "weeks" | "months"; every?: number; times?: string[]; weekdays?: number[];
  between?: [string, string] | null; month_day?: number | null; month_weekday?: { n: 1 | 2 | 3 | 4 | -1; weekday: number } | null;
  start?: string | null; end?: string | null;
};
/** What a schedule does when an execution cannot read the plant or finds no data. */
export type RetryPolicy = { enabled: boolean; count: number; wait_minutes: number; abort_on_next: boolean };
/** A schedule's record over its latest executions. */
export type ScheduleStats = {
  executions: number; failed: number; retried: number; seconds_min: number | null; seconds_mean: number | null; seconds_max: number | null;
  last_status: string | null; last_change: { at: string; to: string } | null; limit: number;
};

/** What a schedule would queue (POST /api/schedules/preview). */
export type SchedulePreview = {
  executions: number; subjects: string[]; next_runs: string[]; when?: string;
  seconds_each: number | null; workers: number; drain_seconds: number | null; period_seconds: number | null; warning: string;
  recorded_outputs?: RecordedOutput[];
};

export interface Status_ {
  round: { status?: string; source_end?: string | null; duration_seconds?: number; error?: string | null; summary?: { loop_count?: number; status_counts?: Record<string, number> }; unread_loops?: number; failed_tag_count?: number };
  progress: { done: number; total: number } | Record<string, never>; running: boolean;
  schedule: { enabled?: number | boolean; interval_minutes?: number | null; next_run_at?: string | null; last_run_at?: string | null };
  sync: { status?: string; found?: number; added?: number; updated?: number; disabled?: number; error?: string; at?: string };
  service_key: boolean; loop_count: number;
}

export interface MethodSpec {
  method_id: string; name: string; label?: string; application?: string; block_id?: string | null; gate?: boolean; version: string; maturity: string;
  description: string; assumptions?: string[]; limitations?: string[]; required_signals: string[];
  references: Array<Record<string, unknown>>; formula?: string | null;
  parameters: { properties?: Record<string, Record<string, unknown>> }; configured_defaults?: Record<string, unknown>;
}

export interface MethodGroup { group_id: string; name: string; description: string; role: string; method_count: number }

/** One block's verdict in a run: a status, a score (100 is best) and a sentence. */
export type BlockResult = { status: string; value: number | null; message: string; label?: string };
/** What an algorithm's output blocks gave in a run (a result, a series, a message). */
export type AlgorithmOutput = { node_id: string; kind: string; name: string; key: string; status: string; value: number | null; message: string; triggered?: boolean; text?: string };

/** What an algorithm is for, written by people (empty: generated from the diagram). */
export type AlgorithmDocs = { purpose: string; assets: string; when: string; reading: string; assistant: string };
export const DOC_FIELDS = ["purpose", "assets", "when", "reading", "assistant"] as const;
export const EMPTY_DOCS: AlgorithmDocs = { purpose: "", assets: "", when: "", reading: "", assistant: "" };

/** What an algorithm works on: control loops, signals, or the assets it names. */
export type SubjectKind = "loop" | "signal" | "asset";

/** When an algorithm on assets runs, and what each run reads (seconds). */
export type AssetTiming = { cycle_seconds: number; window_seconds: number; step_seconds: number };
export const DEFAULT_TIMING: AssetTiming = { cycle_seconds: 60, window_seconds: 1800, step_seconds: 5 };
/** A process model (FMU) published to Link: one block of the Models library. */
export type ModelRow = { model_id: string; block_id: string; name: string; builtin: boolean; origin?: string | null };
/** A new algorithm on assets around a model (`/api/models/<id>/starter`). */
/** ``GET /api/models/examples``: a Simulator example model algorithm, and whether it exists. */
export type ModelExample = { algorithm_id: string; name: string; description: string; exists: boolean };
export type ModelExampleCreated = { algorithm_id: string; name: string; assets: string[]; calibrated: boolean; problem: string };
export type ModelStarter = { name: string; description: string; subject_kind: "asset"; diagram: Diagram; timing: AssetTiming };

/** ``GET /api/algorithms``: a block diagram that judges loops, signals or assets. */
/** One saved version of an algorithm (versions on top of its page). */
/** ``GET /api/algorithms/repeated``: a copy from Twin that repeats another algorithm of the site. */
export type RepeatedAlgorithm = { algorithm_id: string; name: string; same_as: { algorithm_id: string; name: string }; schedules: Array<{ schedule_id: string; name: string }> };
export type AlgorithmVersion = { version: number; name: string; description: string; saved_at: string | null; saved_by: string; current: boolean; version_name?: string; version_note?: string };

/** Where an algorithm's runs go on the compute workers (docs/compute.md, "Environments and sizes"). */
export type ComputePlacement = { environment: string; size: "small" | "medium" | "large" };
export type ComputeOffer = { suite: boolean; environments: string[]; sizes: string[]; workers: number; error?: string };

export interface Algorithm {
  algorithm_id: string; name: string; description: string; system: boolean; subject_kind: SubjectKind;
  diagram: Diagram; check: DiagramCheck; docs: AlgorithmDocs; docs_generated: AlgorithmDocs;
  method_ids: string[]; aliases?: string[]; created_at?: string | null; updated_at?: string | null; docs_problems?: string[];
  timing?: AssetTiming; assets?: string[];
  /** PlantCraft equipment types whose every asset it also runs on, subtypes included (A20). */
  asset_types?: string[];
  /** Where its runs go on the suite's compute workers: the environment (image) and the size. */
  compute?: ComputePlacement;
  /** Who wrote it ("PlantCraft" for the ones that ship), who answers for it, its tags and the
   * group whose members edit it; each save is one version more. */
  author: string; owner: string; owner_name: string; tags: string[]; group: { id: string; name: string } | null;
  version: number; used_by: number | null; editable: boolean;
}

export type UserGroup = { id: string; name: string };

/** An asset an algorithm on assets may name (``GET /api/asset-choices``). */
/** A Deviation (T²) block's calibration: the residuals' mean and covariance in normal operation. */
export type Calibration = { outputs: string[]; mean: number[]; cov: number[][]; std?: number[]; samples: number; warnings?: string[]; asset?: string; start?: string; end?: string };
export type CalibrationAnswer = { node_id: string; asset_id: string; calibration: Calibration; outputs: string[]; std: number[]; samples: number; warnings: string[]; runs: number; used: number; skipped: number; skipped_reason: string; period: { start: string; end: string; every: number } };
export type AssetChoice = { id: string; name: string; kind: string; path: string; roles: string[] };

/** An algorithm's latest run on one of its assets (``GET /api/algorithms/<id>/runs``). */
export type AssetRun = {
  algorithm_id: string; asset_id: string; asset_name: string; status: string; value: number | null; message: string;
  error: string | null; analyzed_at: string | null; window_end: string | null; outputs: AlgorithmOutput[]; blocks: Record<string, BlockResult>;
};

/** ``GET /api/blocks``: the palette. */
/** Who made a block and which version it is, beside its contract (``GET /api/blocks``). */
export type BlockMeta = {
  family: string; number: number | null; current: boolean; origin: string;
  author: string; author_name: string; owner: string; owner_name: string; tags: string[];
  site: boolean; copyable?: boolean; updated_at: string | null;
};
export type CatalogBlock = BlockCatalog["blocks"][number] & BlockMeta & { version: string };
export type Blocks = { libraries: BlockCatalog["libraries"]; blocks: CatalogBlock[]; open_libraries: string[] };
export type BlockVersion = { block_id: string; number: number; name: string; description: string; contract?: string; author: string; author_name: string; created_at: string | null; shipped?: boolean };
export type BlockUse = { algorithm_id: string; name: string; system: boolean; block_id: string; number: number | null; current: boolean };
/** One block's page; `number` is the version shown (``?version=``), `in_use` the one selected for use. */
export type BlockDetail = CatalogBlock & { markdown: string; versions?: BlockVersion[]; used_by: BlockUse[]; editable?: boolean; locked?: boolean; in_use?: number | null };
export type BlockSource = { title: string; filename: string; source: string; line: number };
export type BlockCode = { site: boolean; number: number | null; sources: BlockSource[] };
export type FilePortType = "series" | "state" | "number" | "result" | "intervals";
export type BlockFilePort = {
  port: string; type: FilePortType; types?: FilePortType[]; label?: string; description?: string; unit?: string;
  required?: boolean; multiple?: boolean; record?: boolean;
  /** An output's normal range and which way is good (``higher`` or ``lower``). */
  low?: number | null; high?: number | null; better?: "higher" | "lower" | null;
};
export type BlockFileParameter = {
  name: string; type: "number" | "integer" | "boolean" | "text" | "choice"; title?: string; description?: string;
  default?: unknown; unit?: string; minimum?: number | null; maximum?: number | null; choices?: string[];
};
/** A block file (``plantcraft-block/1``): what a site block's version holds, imported and exported. */
export type BlockFileDoc = {
  format?: string; block_id?: string; name: string; library: string; group?: string; tags?: string[]; origin?: string;
  version?: { number: number; name: string; description: string }; author?: string; owner?: string;
  docs: { summary: string; description?: string; reading?: string; assumptions?: string[]; limitations?: string[]; formula?: string; references?: string[] };
  inputs: BlockFilePort[]; outputs: BlockFilePort[]; parameters: BlockFileParameter[]; runs_on_missing?: boolean;
  /** Its picture (round 9 M2): a data URL, "" or absent for none. */
  image?: string; code: string;
};
export type BlockCheck = { valid: boolean; problems: string[]; block_id?: string; contract_changed?: boolean; used_by?: number };
export type BlockSaved = { block_id: string; number?: number; pinned: string; contract_changed?: boolean; used_by?: BlockUse[] };
export type BlockTestAnswer = {
  check: DiagramCheck; skipped: string[]; asset_id?: string; asset_name?: string;
  window?: { start: string; end: string; step: number } | null;
  inputs?: Record<string, TraceValue>; outputs?: Record<string, TraceValue>;
};

/** ``POST /api/algorithms/test``: the diagram run on one loop, with what every wire carried. */
export type AlgorithmTest = {
  check: DiagramCheck; loop_id?: string; source_start?: string; source_end?: string;
  summary?: LoopSummary & { verdict?: BlockResult & { name?: string }; window?: { start: string; end: string; step: number } };
  results?: MethodResult[]; trace?: DiagramTrace;
  /** A test on an asset: which one. */
  asset_id?: string; asset_name?: string;
};

export interface SignalOption { id: string; name: string; unit?: string; description?: string }

export interface HelpBlock { type: "p" | "ul"; text?: string; items?: string[] }
export interface HelpSection { id: string; title: string; blocks: HelpBlock[] }
export interface MethodHelpEntry { method_id: string; label: string; summary: string }
export interface MethodHelp {
  method_id: string; label: string; title: string; summary: string; sections: HelpSection[];
  parameters: Array<{ key: string; title: string; meaning: string; default: string; configured?: string | null }>;
  references: Array<Record<string, unknown>>; formula?: string | null; maturity?: string; required_signals: string[];
}
export interface LoopTypeDefaults {
  loop_type: string | null; profile_id: string; profile_name: string; why: string;
  parameters: Array<{ method_id: string; method: string; values: Record<string, unknown> }>;
}

/** What `<prefix>assets/<id>` opens (`GET /api/assets/<id>`). */
export interface AssetLink {
  asset_id: string;
  covered: boolean;
  loop_id: string | null;
  reason: string | null;
  /** An asset with no loop: the quality of its signals (Signal quality algorithm). */
  name?: string;
  quality?: { status: string; score: number | null; usable: boolean | null; summary: string };
  signals?: Array<{ role: string; signal: string; status: string | null; quality: number | null; message: string }>;
  /** The algorithms on assets that run on it. */
  runs?: AssetRun[];
  /** The latest result of every algorithm on it: its loop's, Signal quality's, the rest. */
  results?: ResultRow[];
}

/* ------------------------------------------------------- signal quality */

/** Signal verdict: good, suspect, bad, unknown; "off" when switched off; null when never checked. */
export type SignalStatus = "good" | "suspect" | "bad" | "unknown" | "off" | string;

export interface SignalRow {
  id: string; name: string; unit: string; source: string; kind: string; description: string;
  // The source's kind (opcua, pi_web_api, csv, derived); sampled: laboratory or manual samples.
  source_kind?: string; sampled?: boolean;
  roles: string[]; assets: string[]; low: number | null; high: number | null; enabled: boolean; missing: boolean;
  status: SignalStatus | null; quality: number | null; apt: boolean | null; limiting: string | null; message: string;
  checked_at: string | null; flagged?: string[];
}

export interface QualityEvent { start_time: string; end_time: string; label: string; details?: Record<string, unknown> }

export interface CheckResult {
  check: string; name: string; status: string; score: number; message: string;
  metrics?: Record<string, unknown>; events?: QualityEvent[];
}

export interface Verdict {
  status: SignalStatus; quality: number | null; apt: boolean | null; limiting: string | null; message: string;
  checked_at: string; window_start: string | null; window_end: string | null; checks: CheckResult[]; saved?: boolean;
}

export interface SignalSettings {
  low?: number | null; high?: number | null; reference?: string | null;
  checks_off?: string[] | null; checks_on?: string[] | null; parameters?: Record<string, Record<string, unknown>> | null;
  sampling?: "lab" | "continuous" | null; sample_interval_minutes?: number | null;
}

export interface SignalDetail extends SignalRow {
  settings: SignalSettings; processcraft_limits: { low: number | null; high: number | null }; verdict: Verdict | null;
}

export interface Points { t: string[]; v: Array<number | string | null> }
export interface SignalData { signal: string; start: string; end: string; resampled: boolean; series: Points; reference: Points | null }
/** A signal against the lab results of its reference (GET /api/signals/{id}/lab). */
export interface LabSample { t: string; lab: number; online: number | null; corrected: number | null; status: "approved" | "entered" | "rejected" | string; approved_at: string | null }
export interface SignalLab {
  signal: string; reference: string; start: string; end: string;
  /** False: the reference has no laboratory times, each value counts as known when taken. */
  timed: boolean;
  samples: LabSample[]; used: number; health: number | null; health_corrected: number | null; bias: number | null;
  bias_series: { t: string[]; v: number[] }; corrected: { t: string[]; v: number[] };
}
export interface HistoryPoint { checked_at: string; status: SignalStatus; quality: number | null }

/** One run of the Signal quality algorithm. */
export interface QualityRun {
  id: number; started_at: string; finished_at: string | null; status: string; trigger: string; started_by: string;
  window_start: string | null; window_end: string | null; signals: number | null; counts: Record<string, number> | null;
  duration_seconds: number | null; error: string | null;
  /** The signals this run judged whose latest verdict it still is, worst first (one run's page). */
  results?: QualityRunResult[];
}

export interface QualityRunResult {
  signal_id: string; name: string; checked_at: string; status: string; quality: number | null;
  apt: boolean; limiting: string | null; message: string;
}

export interface SignalOverview {
  signals: number; counts: Record<string, number>; apt_share: number | null; mean_quality: number | null;
  by_check: Array<{ check: string; name: string; bad: number; suspect: number }>;
  by_source: Array<{ source: string; total: number; bad: number; suspect: number }>;
  worst: SignalRow[]; last_run: QualityRun | null; running: boolean;
}

export interface CheckParameter {
  name: string; label: string; help: string; type: string; default: unknown; value: unknown;
  minimum?: number | null; maximum?: number | null;
}

export interface CheckSpec {
  id: string; name: string; description: string; maturity: string; formula?: string | null;
  assumptions: string[]; limitations: string[]; references: Array<Record<string, unknown>>; action: string; text_signals: boolean;
  parameters: CheckParameter[]; enabled: boolean;
}

/** The Signal quality algorithm (GET /api/signal-quality). */
export interface SignalAlgorithm {
  id: string; name: string; description: string; system: boolean;
  settings: { window_hours: number; enabled_checks: string[] | null; check_parameters: Record<string, Record<string, unknown>> };
  schedule: { schedule_id?: string; enabled?: number | boolean; interval_minutes?: number | null; next_run_at?: string | null; last_run_at?: string | null };
  checks: CheckSpec[]; running: boolean; progress: { running?: boolean; done?: number; total?: number };
  sync: { status?: string; found?: number; added?: number; updated?: number; missing?: number; error?: string; at?: string };
  signal_count: number;
}

export interface SyncResult { found: number; added: number; updated: number; missing: number }

/** Per day of the last week (GET /api/overview). */
export interface SignalDay { day: string; signals: number; good: number; suspect: number; bad: number; unknown: number; mean_quality: number | null }
export interface LoopDay { day: string; loops: number; mean_health: number | null; below_60: number }

export interface Overview {
  signals: SignalOverview;
  loops: {
    total: number; counts: Record<string, number>; mean_health: number | null; worst: LoopRow[];
    last_round: Status_["round"] | null; running: boolean;
  };
  week: { signals: SignalDay[]; loops: LoopDay[] };
  dashboard_url: string; round_id: string;
}

/** A help browser page (GET /api/help/docs). */
export interface HelpDocEntry { id: string; title: string; category: string }

/** A likely cause ranked from the findings (``report/causes.py``), with what to do first. */
export interface LikelyCause { cause_id: string; cause: string; strength: number; evidence: Array<{ method_id: string; finding: string }>; action: string }

/** A result's headline: the measure that decided it (a signal's quality, a loop's health). */
export type Measure = { label: string; value: number | null; format: "score" | "percent" | "number"; unit?: string };
/** ``GET /api/results``: one subject Link judged, in the suite's status words. */
export type ResultRow = {
  kind: string;
  id: string;
  name: string;
  caption: string;
  area: string;
  status: "ok" | "warning" | "alarm" | "unknown";
  native_status: string;
  measure: Measure;
  algorithm: { id: string; name: string; version?: number | null };
  /** The asset's type ("signal", "loop" or the asset's own type) and its label. */
  asset_type: string; asset_type_label: string;
  /** The algorithm's tags and responsible group. */
  tags: string[]; group: { id: string; name: string } | null;
  limiting: string | null;
  finding: string;
  at: string | null;
  path: string;
};
export type FilterOption = { id: string; label: string; count: number };
/** The filters of Results, beside the status: each a comma list in the address. */
export const RESULT_FILTERS = ["algorithm", "tag", "asset_type", "group"] as const;
export type ResultFilter = (typeof RESULT_FILTERS)[number];
export type ResultQuery = Partial<Record<ResultFilter | "status", string[]>> & { q?: string };
export type ResultList = {
  total: number; counts: { kind: Record<string, number>; status: Record<string, number> };
  options: Record<ResultFilter, FilterOption[]>; kinds: Array<{ id: string; label: string }>; items: ResultRow[];
};


/** One run of any algorithm (Results, Runs view). `state` is in the suite's words, or running/pending. */
export type RunRow = {
  id: string; path: string; algorithm: { id: string; name: string }; subject: string; subject_path?: string;
  state: string; status_label: string; started_at: string | null; duration_seconds: number | null;
  finding: string; trigger: string; by: string;
};

export type UsageSubject = { id: string; name: string; caption: string; status: string; health: number | null; path: string };
export type AlgorithmUsage = {
  algorithm: { id: string; name: string };
  schedules: Schedule[];
  subjects: { kind: string; count: number; every: boolean; items: UsageSubject[] };
};

/** One item of the queue (GET /api/executions): an algorithm on a loop or an asset, a round, a replay. */
export type Execution = {
  id: string; name: string; work: "loop" | "round" | "asset" | "replay"; work_label: string;
  algorithm: { id: string; name: string } | null; subject: string; subject_path: string | null; path: string | null;
  schedule: { id: string; name: string } | null; status: string; state: string; status_label: string; kind: string;
  priority: number; requested_at: string | null; due_at: string | null; started_at: string | null; finished_at: string | null;
  wait_seconds: number | null; duration_seconds: number | null; attempts: number; max_attempts?: number | null; progress: { done: number; total: number } | null;
  error: string; by: string; worker: string; can_cancel: boolean; can_rerun: boolean;
};
export type ExecutionList = { total: number; items: Execution[]; works: Record<string, string>; statuses: Record<string, string> };

/** ``GET /api/executions/groups``: a schedule (or the manual runs) as Executions opens it. */
export type ExecutionGroup = {
  id: string; name: string; kind: string; algorithm: { id: string; name: string; version?: number | null } | null;
  subject_kind: string; subjects: number; counts: Record<"ok" | "warning" | "alarm" | "unknown", number>;
  enabled: boolean; priority: number; owner: string; last_run_at: string | null; next_run_at: string | null;
  interval_minutes: number | null; cadence: string | null; when?: string; path: string; schedule_path: string | null;
};
/** One subject of a group with its latest result; ``status_label`` is the discreet word (High, Critical...). */
export type GroupSubject = { id: string; name: string; state: string; status_label: string; measure: Measure | null; finding: string; at: string | null; path: string };
export type GroupPast = { at: string | null; state: string; status_label: string; value: number | null; path?: string | null; id?: string | null; version?: number | null; duration_seconds?: number | null; by?: string; sampled?: boolean };
/** One output of a subject's latest result: an algorithm's output, a loop's method or a
 * signal's check (round 9, D11). */
export type SubjectOutput = { name?: string; key?: string; kind?: string; status?: string; state?: string; status_label?: string; value?: number | null; message?: string };

export type SubjectHistory = {
  group: ExecutionGroup; subject: GroupSubject; algorithm: { id: string; name: string; version?: number | null } | null;
  outputs: SubjectOutput[];
  execution_id: string | null; subject_path: string; series: { id: string; name: string; unit: string }[];
  versions: string | null; executions: GroupPast[]; detail_kept: number; since: string;
  /** How many of a subject's last runs keep what each wire carried (round 10). */
  samples_kept: number;
  /** The last run (Open the last run); ``run`` is the one ``?run=`` asked for (none: deleted). */
  last_run: SubjectRun | null; run: SubjectRun | null;
};
/** One run as its page draws it: each block's verdict, what each wire carried (its samples when
 * ``sampled``, one of the last runs; else its last value), the window. */
export type SubjectRun = {
  id: string | null; at: string | null; on: string; version: number | null; sampled?: boolean;
  blocks: Record<string, BlockResult>; wires: DiagramTrace; outputs: AlgorithmOutput[];
  window: { start: string; end: string; step?: number } | null; signals: Record<string, string>;
};
export type OwnSeries = { signal: string; t: string[]; v: (number | string | null)[]; error?: string };


/** One save of a method's or a check's defaults (GET /api/methods/<id>/defaults/versions). */
export type DefaultsVersion = { number: number; parameters: Record<string, unknown>; description: string; saved_by: string; saved_at: string; current: boolean };

/** PI settings from a model fitted to the loop's last window (Lambda/IMC), read only (A12). */
export interface TuningSuggestion {
  available: boolean; reason?: string; reliable?: boolean; caveats?: string[]; action?: "reverse" | "direct";
  model?: { gain: number; tau_seconds: number; dead_time_seconds: number; r2: number; samples?: number };
  settings?: Array<{ choice: "tight" | "moderate" | "robust"; lambda_seconds: number; kc: number; ti_seconds: number }>;
  source_start?: string | null; source_end?: string | null;
}

/** A third-party multivariable controller, read from its own signals (`GET /api/apc`, A16/A17). */
export interface ApcSummary {
  on_now: boolean;
  on_pct: number | null;
  mvs: number;
  mvs_in_service: number;
  mv_in_service_pct: number | null;
  cvs: number;
  cvs_at_limit: number;
  cv_at_limit_pct: number | null;
  constraints_active: number;
  state: "ok" | "warning" | "alarm" | null;
}

export interface ApcVariable {
  id: string;
  name: string;
  kind: "mv" | "cv";
  signals: Record<string, string>;
  value: number | null;
  lo: number | null;
  hi: number | null;
  target: number | null;
  shadow_price: number | null;
  in_service: boolean;
  at: "lo" | "hi" | null;
  in_service_pct: number | null;
  at_limit_pct: number | null;
  at_lo_pct: number | null;
  at_hi_pct: number | null;
}

export interface ApcConstraint {
  variable_id: string;
  name: string;
  kind: "mv" | "cv";
  side: "lo" | "hi";
  hours: number;
  share_pct: number | null;
  active_now: boolean;
  shadow_price: number | null;
  worth_1pct: number | null;
}

export interface ApcController {
  id: string;
  name: string;
  parent_id: string | null;
  vendor: string;
  cost_unit: string;
  summary: ApcSummary;
  variables?: ApcVariable[];
  constraints: ApcConstraint[];
  failed: string[];
  since?: string;
  until?: string;
}

export interface ApcList { since: string | null; until: string | null; controllers: ApcController[] }

/** The plant map (A6): each loop's KPIs, banded on one scale (higher is better). */
export type PlantMapBand = "good" | "fair" | "poor" | "bad" | "none";
export interface PlantMapLoop {
  loop_id: string; name: string; area: string; criticality: string; weight: number; status: string | null;
  values: Record<string, number | null>; bands: Record<string, PlantMapBand>;
}
export interface PlantMap { kpis: Array<{ key: string; label: string }>; bands: Array<{ band: PlantMapBand; from: number }>; loops: PlantMapLoop[] }

/** A PlantCraft asset type an algorithm on assets can run on every asset of (A20). */
export interface AssetTypeChoice { id: string; name: string; parent?: string | null; roles: string[] }
