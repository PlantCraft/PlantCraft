/** The shapes the PlantCraft Models API answers (src/modelcraft/api). */
import type { BlockSpec, Diagram as BlockDiagram } from "@plantcraft/ui/blockEditor";

export type { BlockDiagram };

export interface Me {
  username: string; name: string; level: string; access: string; role: string;
  can_edit: boolean; is_admin: boolean; processcraft_url: string; version: string; service_key: boolean;
}

export interface ProjectFile { path: string; bytes: number; updated_by: string; updated_at: string }

export interface Project {
  id: string; name: string; description: string; example: boolean;
  created_by: string; created_at: string; updated_by: string; updated_at: string;
  files?: ProjectFile[] | number; bytes?: number; classes?: ClassInfo[];
  kind?: "project" | "library";
  /** In the list: how many models, studies, simulations and FMU exports it holds. */
  models?: number; studies?: number; simulations?: number; exports?: number;
}

export interface ClassInfo {
  name: string; short: string; restriction: string; comment: string; partial: boolean;
  file: string; line: number; simulable: boolean;
  experiment: { StartTime?: number; StopTime?: number; Interval?: number; Tolerance?: number };
}

export interface FileContent { path: string; content: string; updated_by: string; updated_at: string }
export interface Revision { id: number; path: string; saved_by: string; saved_at: string; bytes: number; version_name?: string; version_note?: string }

export interface Message {
  level: "error" | "warning" | "info"; text: string; file: string | null; own?: boolean;
  line?: number | null; column?: number | null; end_line?: number | null; end_column?: number | null;
}

export interface CheckResult { ok: boolean; model: string; messages: Message[]; summary: string; seconds: number }

export type Point = [number, number];
export interface Graphic {
  kind: "Line" | "Polygon" | "Rectangle" | "Ellipse" | "Text" | "Bitmap";
  origin: Point; rotation: number;
  points?: Point[]; color?: number[] | null; pattern?: string; thickness?: number; arrow?: [string, string]; arrowSize?: number; smooth?: string;
  lineColor?: number[] | null; fillColor?: number[] | null; fillPattern?: string; lineThickness?: number;
  extent?: [Point, Point]; radius?: number; startAngle?: number; endAngle?: number;
  text?: string; fontSize?: number; textColor?: number[] | null; horizontalAlignment?: string;
}
export interface Layer { extent: [Point, Point]; graphics: Graphic[] }
export interface Placement { extent: [Point, Point]; origin: Point; rotation: number }
export interface Parameter { name: string; type: string; comment: string; default: string | null; value: string | null; set: string | null; unit: string; group: string; tab: string }
export interface ConnectorInfo { name: string; type: string; placement: Placement; icon: Layer; direction: string }
export interface ComponentInfo {
  name: string; type: string; restriction: string; comment: string; inherited: boolean;
  placement: Placement; icon: Layer; connectors: ConnectorInfo[]; parameters: Parameter[];
  values: Record<string, string>; connector: boolean; direction: string;
}
export interface Connection { from: string; to: string; points: Point[]; color: number[] | null; thickness: number; inherited: boolean }
export interface Diagram {
  name: string; restriction: string; comment: string; diagram: Layer; icon: Layer;
  components: ComponentInfo[]; connections: Connection[]; parameters: Parameter[];
  inputs: string[]; outputs: string[];
  documentation: { info: string; revisions: string }; source?: string | null; messages?: Message[];
}

export interface LibraryEntry { name: string; short: string; restriction: string; partial: boolean; comment: string; has_children: boolean }
export interface LibraryClass extends Diagram, LibraryEntry {}

export interface RunnerState {
  available: boolean; reason: string; omc: string; libraries: Record<string, string>;
  workers?: number; queued?: number; running?: number;
  library: { ready: boolean; classes: number; building: boolean; error: string }; allow_external: boolean;
}

export type RunStatus = "queued" | "running" | "done" | "failed" | "cancelled";

export interface Run {
  id: string; project_id: string; project_name: string; model: string; kind: "simulate" | "fmu";
  status: RunStatus;
  options: Record<string, any>; messages: Message[]; result: Record<string, any>;
  summary: string; seconds: number | null; label: string; created_by: string; created_at: string;
  started_at: string | null; finished_at: string | null;
  study_id?: string; variant?: Record<string, number | boolean | string>; priority?: number;
  /** How far a running simulation is, 0 to 1 (null when it is not running). */
  progress?: number | null;
  study?: { id: string; name: string; kind: StudyKind } | null;
}

/** A study: one model simulated once (single), over a sweep of parameter values (sweep), or the
 * project's quick simulations of that model (quick). */
export type StudyKind = "quick" | "single" | "sweep" | "optimization";

/** One varied input, parameter or simulation setting (`@stop`, `@intervals`, `@tolerance`, `@method`). */
export interface SweepItem { name: string; mode: "range" | "list"; start?: number; stop?: number; count?: number; values?: Array<number | boolean | string> }

/** Where runs go on the compute workers (docs/compute.md, "Environments and sizes"). */
export type ComputePlacement = { environment: string; size: "small" | "medium" | "large" };
export type ComputeOffer = { suite: boolean; environments: string[]; sizes: string[]; workers: number };

export interface StudySpec {
  options: { start: number; stop: number; intervals: number; tolerance: number; method: string; overrides: Record<string, number | boolean>; time_limit?: number; plant?: Record<string, unknown>;
    /** Where its runs go on the suite's compute workers (none: any worker, size small). */
    compute?: ComputePlacement;
    /** The model's inputs the study drives (round 9 M6). */
    inputs?: Record<string, { shape: "constant" | "step" | "ramp"; value?: number; before?: number; at?: number; end?: number }> };
  sweep: SweepItem[];
  indicators: string[];
  /** An optimization study's settings (what it changes, makes best and keeps within bounds). */
  optimization?: OptimizationSpec;
}

export interface DecisionVariable { name: string; start: number; min: number; max: number }
export type Goal = "minimize" | "maximize" | "target";
export interface OptimizationConstraint { variable: string; statistic: string; op: "<=" | ">="; value: number }
export interface OptimizationSpec {
  variables: DecisionVariable[];
  objective: { variable: string; statistic: string; goal: Goal; target?: number | null };
  constraints: OptimizationConstraint[];
  method: "nelder-mead" | "cobyla" | "slsqp";
  max_simulations: number;
}
/** One simulation the optimizer asked for: its values, the objective, each constraint's margin. */
export interface Evaluation { index: number; run_id: string; values: Record<string, number>; objective: number | null; cost: number; constraints: Array<number | null>; feasible: boolean; failed: boolean }
export interface OptimizationState {
  status: "running" | "waiting" | "done" | "stopped" | "failed";
  message?: string; converged?: boolean; method?: string; started_at?: string; finished_at?: string;
  evaluations: Evaluation[]; best?: Evaluation | null;
}

export interface StudyCounts { queued: number; running: number; done: number; failed: number; cancelled: number; total: number }

export interface Study extends StudyCounts {
  id: string; project_id: string; project_name: string; model: string; name: string; kind: StudyKind;
  description: string; spec: StudySpec | Record<string, never>; created_by: string; created_at: string; updated_at: string;
  last_run_at?: string | null;
  runs?: Run[];
  optimization?: OptimizationState | null;
}

export interface StudyPreview { count: number; limit: number; warn_above: number; seconds_each: number | null; seconds_total: number | null }

export interface Envelope { name: string; runs: number; time: number[]; min: Array<number | null>; p5: Array<number | null>; p50: Array<number | null>; p95: Array<number | null>; max: Array<number | null> }

export interface StudySeries {
  name: string;
  series: Array<{ run_id: string; label: string; variant: Record<string, number | boolean | string>; time: number[]; values: Array<number | null> }>;
  envelope: Envelope | null;
}

export interface StatisticRow { variable: string; statistic: string; n: number; mean: number | null; std: number | null; min: number | null; p5: number | null; p50: number | null; p95: number | null; max: number | null }

export interface QueueState { queued: number; running: number; workers: number; busy: number; running_runs: Run[]; queued_runs: Run[] }

/** A block library: Modelica classes every project may use, in a group (Equipment, Control…). */
export interface BlockLibrary extends Project {
  kind: "library"; group: string; packages: string[];
  blocks: Array<{ name: string; short: string; restriction: string; comment: string; partial: boolean; file: string }>;
}

export interface Variable {
  name: string; description: string; unit: string; type: string; kind: string; start: string | null;
  column: number | null; final: number | null; constant: boolean; protected?: boolean;
}

export interface SeriesAnswer {
  series: Array<{ name: string; time: number[]; values: Array<number | null> }>;
  missing: string[];
  compare: Array<{ name: string; signal: string; time: number[]; values: number[] }>;
}

export interface SignalOption { id: string; name: string; unit: string; description: string }
export interface AssetRuns { asset: { id: string; name: string; kind: string }; signals: string[]; runs: Run[] }

/** A model's simulation settings, kept in its class's annotation (modelica/blockdiagram.py). */
export interface SimSettings { start: number; stop: number; interval: number; tolerance: number; solver: string }

/** A model in the list (`GET /api/models`): drawn as a diagram, or written as code. */
export interface ModelItem {
  project_id: string; project: string; group: string; example: boolean;
  model: string; name: string; description: string; file: string;
  diagram: boolean; blocks: number; settings: SimSettings; updated_by: string; updated_at: string;
}

/** One model with its diagram, read from its Modelica text. */
export interface ModelDetail {
  project_id: string; project: string; group: string; example: boolean;
  model: string; name: string; description: string; file: string;
  updated_at: string | null; updated_by: string | null;
  /** The name of the version in use and what changed in it (empty for older saves). */
  version_name?: string; version_note?: string;
  diagram: BlockDiagram; settings: SimSettings; problems: string[]; editable: boolean;
  /** The earlier save this is (a version opened read-only, round 9 M4); null for the one in use. */
  revision?: number | null;
  /** A model written as code, as the one block of its diagram (its ports and parameters). */
  code_block?: BlockSpec | null;
}

/** A model whose diagram places a block (`GET /api/catalog/<id>/used-by`). */
export interface BlockUse { project_id: string; model: string; name: string; example: boolean; count: number }

/** A block of the catalog with where it lives and its Modelica text (`GET /api/catalog/<id>`). */
export type CatalogBlock = BlockSpec & { library_name: string; library_group: string; example: boolean; file: string; code: string;
  /** The version in use of a site block: who saved it, when, and what changed. */
  updated_at?: string | null; updated_by?: string | null; version_name?: string; version_note?: string };

/** A tracking (M3): a model simulated against the plant on a schedule, its error kept as signals. */
export interface TrackingConfig {
  inputs: Record<string, string>; compare: Record<string, string>;
  window_minutes: number; every_minutes: number; step_seconds: number | null; intervals: number;
  overrides: Record<string, number | boolean>; limits: Record<string, number>;
}
export interface TrackingMetrics { mae: number | null; bias: number | null; max: number | null; last: number | null; n: number }
export interface Tracking {
  id: string; project_id: string; model: string; name: string; config: TrackingConfig;
  enabled: boolean; next_at: string | null;
  last: { status?: string; run_id?: string; at?: string; metrics?: Record<string, TrackingMetrics>; written?: number; detail?: string };
  /** The variables off the plant now (their mismatch event open). */
  open: string[];
  /** Each compared variable's error signal in PlantCraft. */
  signals: Record<string, string>;
  created_by: string; created_at: string; updated_at: string;
}
export type TrackingBody = Omit<TrackingConfig, "step_seconds"> & { project_id: string; model: string; name: string; step_seconds?: number | null; enabled: boolean };
