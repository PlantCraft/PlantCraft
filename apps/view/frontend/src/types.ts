import type { DiagramData, DiagramDraft, SymbolDef } from "./diagrams/model";

export type Kind = "stat" | "gauge" | "trend" | "bar" | "table" | "scatter" | "text" | "diagram" | "apc";
export type Aggregation = "last" | "mean" | "min" | "max" | "std";
export type State = "ok" | "warning" | "alarm" | "unknown" | "none";
/** The level of a threshold step: a state, or "none" for a colour that is not a state. */
export type Level = "ok" | "warning" | "alarm" | "none";

export interface Me {
  username: string; name: string; level: string; access: string; role: string; can_edit: boolean; is_admin: boolean;
  processcraft_url: string; version: string; public_links: boolean;
}

/** One signal of a card: a signal id (may hold `${var}`), an asset (or `$var`) and a role (`*`: every
 * signal of the asset, `roles` to keep some), or another app's result. */
export interface CardItem { signal_id?: string | null; asset_id?: string | null; role?: string | null; roles?: string[]; result?: string | null; label?: string }

/** A threshold: from `value` up (none: the base step below all others). `color` "" is the level's. */
export interface Step { value?: number | null; color?: string; level?: Level }
export interface Thresholds { mode?: "absolute" | "percentage"; steps: Step[]; show?: "off" | "lines" | "area" | "lines+area" }
export interface Mapping { type: "value" | "range" | "text"; value?: string; low?: number | null; high?: number | null; text?: string; color?: string; level?: "" | "ok" | "warning" | "alarm" }
/** How a card shows its values (Grafana's field config); every option optional (none: inherited, else automatic). */
export interface FieldConfig {
  unit?: string | null; min?: number | null; max?: number | null; decimals?: number | null;
  display_name?: string | null; no_value?: string | null;
  color_mode?: "thresholds" | "fixed" | "palette" | null; color?: string | null;
  thresholds?: Thresholds | null; mappings?: Mapping[] | null;
  draw?: "lines" | "points" | "lines+points" | "bars" | null; interpolation?: "linear" | "smooth" | "step" | null;
  line_width?: number | null; dash?: "solid" | "dash" | "dot" | "dashdot" | null; fill?: number | null;
  axis?: "auto" | "left" | "right" | "hidden" | null;
  /** The normal (desired) operating range (ISA-101); none: the thresholds' normal step. */
  normal_low?: number | null; normal_high?: number | null;
}
export interface Matcher { by: "role" | "signal" | "name"; value: string }
export interface Override { match: Matcher; field: FieldConfig }
export type TableColumn = "last" | "mean" | "min" | "max" | "std" | "unit" | "time" | "state";
/** What each kind draws (Grafana's panel options): one set for every kind. */
export interface CardOptions {
  graph: "none" | "area"; color_by: "value" | "background" | "none"; show_name: boolean;
  orientation: "auto" | "horizontal" | "vertical";
  bar_style: "bars" | "gauge"; value_labels: "auto" | "always" | "never"; sort: "none" | "asc" | "desc";
  legend: "list" | "table" | "hidden"; legend_place: "bottom" | "right"; legend_values: Array<"last" | "mean" | "min" | "max">;
  tooltip: "all" | "single" | "hidden"; stack: "none" | "normal" | "percent"; connect_gaps: boolean;
  y_scale: "linear" | "log"; y_label: string; soft_min: number | null; soft_max: number | null;
  gauge_style: "dial" | "analog"; threshold_markers: boolean; threshold_labels: boolean;
  columns: TableColumn[]; cell: "text" | "color_text" | "color_background" | "bar"; row_color: boolean;
  point_size: number;
}
/** A card drawn once for each value of a variable. */
export interface Repeat { variable: string; direction: "h" | "v"; max_per_row: number }

export interface Card {
  card_id: string; title: string; description?: string; kind: Kind; items: CardItem[]; agg: Aggregation;
  /** A window (`8h`) or an interval variable (`$period`). */
  window: string;
  field: FieldConfig; overrides: Override[]; options: Partial<CardOptions>;
  /** Place (column, row) and size (2 to 12 columns, 1 to 12 rows) on the grid. */
  x?: number | null; y?: number | null; width: number; height: number;
  /** The dashboard page the card is on; none: the first page. */
  page_id?: string | null;
  /** Text cards: the note. */
  text?: string;
  /** Diagram cards: the saved diagram they show. */
  diagram_id?: string;
  /** Multivariable controller cards: the asset of kind `apc` they show. */
  apc_id?: string;
  repeat?: Repeat | null;
}

/** A picker at the top of a dashboard: assets of a kind, a typed list, or time windows. */
export interface Variable {
  name: string; label?: string; type: "asset" | "custom" | "interval";
  asset_kind?: string | null; parent?: string | null; options?: string[];
  multi?: boolean; include_all?: boolean; default?: string;
}
export interface VariableOption { value: string; text: string; group: string | null; description: string }

/** A page (tab) of a dashboard. */
export interface Page { page_id: string; name: string }

export interface DashboardDraft {
  name: string; description: string; context_kind: string | null; refresh_seconds: number;
  variables: Variable[];
  /** No pages: one page without a name. `page_seconds`: full screen turns pages (0: never). */
  pages: Page[]; page_seconds: number; cards: Card[];
  /** The folder ("" = General), tags, the window it opens with (null: each card's own), the
   * cursor its time charts share, full screen without the toolbar. */
  folder_id: string; tags: string[]; default_window: string | null; shared_cursor: boolean; kiosk: boolean;
}

export interface Dashboard extends DashboardDraft {
  dashboard_id: string; created_by?: string | null; created_at?: string; updated_by?: string | null; updated_at?: string;
  public_links?: number; card_count?: number;
  // "suite-health": kept by the suite, read-only (a copy is an ordinary dashboard).
  builtin?: string;
  /** Whether the signed-in person changes it (its folder's editors; false on a public link). */
  can_edit?: boolean;
}

/** A folder of dashboards: who sees and who edits them (`user:<name>`, `group:<id>`; empty: everyone). */
export interface Folder {
  folder_id: string; name: string; description: string; viewers: string[]; editors: string[];
  dashboards: number; reports: number; can_edit: boolean; updated_by?: string | null; updated_at?: string;
}
export interface FolderDraft { name: string; description: string; viewers: string[]; editors: string[] }
/** What a new dashboard can start from, built from the plant's assets. */
export interface Template { template_id: string; name: string; description: string; cards: number; draft: Partial<DashboardDraft> }
export interface Version { version: number; saved_by: string | null; saved_at: string; name: string; cards: number; pages: number }
export interface Directory { people: Array<{ username: string; name: string; role?: string | null; job_title?: string | null }>; groups: Array<{ id: string; name: string; kind?: string | null; members?: string[] }> }

interface ItemBase { label: string; signal: string | null; role?: string | null; asset?: string | null; unit: string; kind: string; low?: number | null; high?: number | null; error: string | null }
export interface ValueRow extends ItemBase { value: number | string | null; at: string | null; agg: string; state: State; summary?: string; stale?: boolean; result?: string }
export interface TableRow extends ItemBase { values: Partial<Record<Aggregation, number | string | null>>; at: string | null; state: State }
export interface Line extends ItemBase { t: string[]; v: Array<number | null> }

export interface CardData {
  card_id: string; kind: Kind; window: string; agg?: string; read_at: string;
  rows?: Array<ValueRow & TableRow>; lines?: Line[];
  range?: { start: string; end: string; step: number; shifted: boolean };
  /** Diagram cards: the diagram with the symbols it draws and its values now, or why it is not
   * shown; `url` (signed in only) is its page. */
  diagram?: PublicDiagram; data?: DiagramData; unavailable?: string; url?: string;
  /** Multivariable controller cards: the controller and its MVs and CVs (read only). */
  apc?: ApcData;
}

/** A manipulated (mv) or controlled (cv) variable of a multivariable controller. */
export interface ApcVariable {
  id: string; name: string; type: "mv" | "cv"; description: string; unit: string;
  value: number | null; lo: number | null; hi: number | null; target: number | null;
  status: number | null; shadow_price: number | null; in_service: boolean | null;
  at_limit: "lo" | "hi" | null; missing: string[];
  t: string[]; value_line: Array<number | null>; target_t: string[]; target_line: Array<number | null>;
}
export interface ApcData {
  controller?: { id: string; name: string; on: boolean | null; mode: string | number | null; vendor: string; cost_unit: string };
  variables?: ApcVariable[];
  counts?: { mv: number; cv: number; in_service: number; at_limits: number };
  error: string | null;
}

/** A diagram as a public link and a dashboard card draw it (no authors or stamps). */
export type PublicDiagram = Omit<DiagramDraft, "folder_id" | "tags"> & { diagram_id: string; symbols: SymbolDef[] };

export interface AssetOption { id: string; name: string; kind: string; parent: string | null; signals: Record<string, string> }
export interface AssetKind { kind: string; count: number; roles: string[] }
export interface SignalOption { id: string; name: string; unit: string; description: string; kind: string }

/** A public link; `expires_at` null opens until revoked (an administrator's choice); `name` and `target` in the administrator's list of every link. */
export interface ShareLink { share_id: string; dashboard_id: string; label: string; created_by: string | null; created_at: string; last_used_at: string | null; expires_at: string | null; target?: ShareTarget; name?: string; path?: string }

export interface AssetDashboards {
  asset: { id: string; name: string | null; kind: string | null; kind_label?: string; description?: string; signals?: Record<string, string> };
  dashboards: Array<{ dashboard_id: string; name: string; description: string; picks_asset: boolean }>;
}
/** An app result the editor can show: on how many assets, and how many keep its history (trends). */
export interface ResultKind { result: string; count: number; history: number }

/** A trend: plots of signals over a relative or fixed period (`/api/trends`). */
/** How a trend line is summarised over its interval, and drawn. */
export type TrendAgg = "mean" | "last" | "first" | "min" | "max";
export interface LineStyle { mode: "lines" | "markers" | "lines+markers"; shape: "linear" | "hv" | "spline"; color: string; width: number; dash: "solid" | "dot" | "dash" | "dashdot"; marker_size: number; axis: "left" | "right" }
/** A line of a trend; `step_seconds` is its own interval (0 = as recorded), null or absent: the trend's. */
export interface TrendLineSpec { signal_id: string; label?: string; agg?: TrendAgg; step_seconds?: number | null; style?: Partial<LineStyle> }
/** A trend line as read: the summary used ("recorded" for the samples as they are) and a note when it fell back. */
/** A laboratory result (`laboratory:<analysis>`): drawn at its sampling time, with its other times. */
export interface LabSample { sampled_at: string; value: number | null; status: "entered" | "approved" | "rejected" | string; received_at?: string | null; approved_at?: string | null }
/** `compare`: an earlier period's line moved onto the trend's time axis; `source`: the index of its line in the plot. */
export type TrendLine = Line & { agg?: TrendAgg | "recorded"; step?: number; style?: LineStyle; note?: string | null; samples?: LabSample[]; compare?: TrendCompare; source?: number }
export interface TrendPlotSpec { title?: string; lines: TrendLineSpec[] }
export interface TrendPeriod { mode: "relative" | "fixed"; window: string; start?: string | null; end?: string | null }
/** An earlier period drawn over the trend's own: the one just before, or a day, a week or four weeks back. */
export type TrendCompare = "previous" | "1d" | "7d" | "28d";
export interface TrendView { plots: TrendPlotSpec[]; period: TrendPeriod; step_seconds: number | null; compare?: TrendCompare[] }
export interface Trend extends TrendView {
  trend_id: string; name: string; description: string; created_by: string | null; created_at: string; updated_by: string | null; updated_at: string;
}
export interface TrendData {
  plots: Array<{ title: string; lines: TrendLine[] }>;
  range: { start: string; end: string; step: number; shifted: boolean };
  read_at: string;
}

/** A report (`/api/reports`): sections read over one period, made into a PDF on a schedule and
 * sent to people and groups in Messages. */
export type SectionKind = "text" | "card" | "events" | "break" | "assistant";
/** ``group_by``: count the period's events by subject, kind, severity or ``payload.<field>``
 * and rank the groups (the most first) instead of listing the latest; "" lists them. */
export interface EventsSpec { kinds: string[]; limit: number; group_by?: string }
/** What an assistant section reads and how the model writes it (prototype, E2). */
export interface AssistantSpec { asset_ids: string[]; children: boolean; analyses: string[]; requirements: string; version: number }
export interface AssistantWritten { run_id: string; version: number; text: string; written_at: string; facts: { assets: number; results: number; events: number } }
export interface AssistantData { kind: "assistant"; assets: number; results: number; events: number; event_counts: Record<string, number>; written: AssistantWritten | null }
export interface AssistantVersion { version: number; requirements: string; feedback: string; run_id: string | null; created_by: string | null; created_at: string }
export interface Analysis { id: string; title: string }
export interface Section {
  section_id: string; kind: SectionKind;
  /** An events section's title (a card keeps its own; a text cell writes its headings in its Markdown). */
  title: string; text: string; card: Card | null; events: EventsSpec | null; assistant?: AssistantSpec | null; width: "full" | "half";
}
export type Weekday = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";
export interface Schedule { every: "off" | "day" | "week" | "fortnight" | "month" | "quarter"; at: string; weekday: Weekday; day: number; /** Cover the last whole calendar period (last week, last month), not the period up to the send. */ closed?: boolean }
export interface ReportDraft {
  name: string; description: string; folder_id: string; period: string; schedule: Schedule;
  recipients: string[]; email: boolean; sections: Section[];
}
export interface ReportRun {
  run_id: string; report_id: string; report_name: string; trigger: "schedule" | "send" | "download";
  status: "running" | "done" | "failed"; requested_by: string | null; started_at: string; finished_at: string | null;
  period_start: string; period_end: string; period: string; sections: number; problems: number;
  summary: string; error: string; recipients: string[]; delivered: number; pdf_bytes: number;
}
export interface Report extends ReportDraft {
  report_id: string; created_by?: string | null; created_at?: string; updated_by?: string | null; updated_at?: string;
  next_run_at: string | null; cadence: string; zone: string;
  /** What it covers if made now (the server's clock). */
  covers: { start: string; end: string }; section_count: number; can_edit: boolean;
  last_run: ReportRun | null; public_links?: number;
}
export type ShareTarget = "dashboard" | "report" | "diagram";
export type ExportFormat = "docx" | "html" | "md";
/** One section as read: its data (a card's, or the events'), or why it could not be read. */
export interface SectionData { section: Section; data: (CardData | EventsData | AssistantData) | null; error: string | null }
export interface EventRow { at: string; kind: string; title: string; subject: string; subject_name: string; summary: string; severity: string }
export interface EventsData {
  kind: "events"; counts: Array<{ kind: string; title: string; count: number; more: boolean }>;
  total: number; events: EventRow[]; range: { start: string; end: string };
  /** A section that counts its events: the largest groups, the most first. */
  group_by?: string; group_head?: string; groups?: EventGroup[]; group_total?: number;
}
export interface EventGroup { key: string; label: string; count: number; share: number; first: string | null; last: string | null; summary: string; severity: string }
/** An event an installed app declares, for an events section's picker. */
export interface EventKind { kind: string; title: string; app: string; description: string; severity: string }
