export type Me = {
  username: string;
  name: string;
  level: string;
  access: string;
  // What the user menu shows: "admin" for a PlantCraft admin, else `access`.
  role: string;
  can_edit: boolean;
  is_admin: boolean;
  processcraft_url: string;
  version: string;
};

export type SourceState = { status: string; detail: string; since: number; checked?: number; files?: number };

export type SourceKind = "pi_web_api" | "opcua" | "csv" | "mqtt" | "sparkplug" | "modbus" | "sql" | "derived" | "system" | "calc" | "import";
/** Sources written through the suite (an app's series, the suite's health), never read from a plant. */
export const isWritten = (kind: string) => kind === "derived" || kind === "system";
/** Where a signal's history comes from: read from the source, archived here, or both. */
export type Mode = "source" | "archive" | "both";

export type Source = {
  id: string;
  name: string;
  kind: SourceKind;
  endpoint: string;
  namespace_uri: string;
  username: string;
  password_env: string;
  // Never sent back; only whether one is stored (typed or from the environment).
  has_password: boolean;
  // Effective mode, and the kind's default when the source sets none.
  mode: Mode;
  default_mode: Mode;
  options: Record<string, unknown>;
  enabled: boolean;
  points: number;
  state: SourceState | null;
  // Whether the source tells the quality of its values (else every value counts as good).
  quality_reported?: boolean;
  // A derived source of an app merged into another: the app that took over its work.
  retired_into?: string | null;
} & SourceSettings & SourceIntegration;

/** The integration around a source (H13): who answers for it (told with an email when it fails),
 * how to reach the team that runs it, and how often a value must arrive (0: not watched). */
export type SourceIntegration = {
  owners: string[];
  contact: string;
  heartbeat_seconds: number;
};

/** A change of a source's state, as the collector saw it (``/api/sources/<id>/history``). */
export type SourceEvent = { at_ms: number; status: string; detail: string };

/** A source's overrides of the general settings for its points; null: the general value. */
export type SourceSettings = {
  retention_days: number | null;
  default_scan_seconds: number | null;
  default_deviation_percent: number | null;
  default_max_seconds: number | null;
};

/** Where a point's setting in effect comes from: its own, its source's, or the general one. */
export type Origin = "point" | "source" | "general" | "profile";
export type PointSetting = "retention_days" | "scan_seconds" | "deviation" | "max_seconds" | "exception";
/** Compression profiles (round 8 D1): standard (the general settings), fine and none. */
export type Profile = "" | "fine" | "none";

/** What a point holds (histcraft/kinds.py): integer, boolean and instant are stored as numbers. */
export type PointKind = "number" | "integer" | "boolean" | "text" | "instant" | "structured" | "runs";

/** A runs point's execution (H2): when it ran, the span of its series and its values. */
export type RunInfo = { run_at: string; start: string; end: string; n: number };
export type RunsSeries = { signal: string; kind: "runs"; runs: { run_at: string; t: string[]; v: (number | null)[] }[] };

export type Point = {
  id: number;
  // The signal id, `<source id>:<tag>`: the key of a point (two sources may share a tag).
  signal: string;
  tag: string;
  source_id: string;
  source_kind: SourceKind;
  // Effective mode, and the point's own override (empty: the source's).
  mode: Mode;
  own_mode: Mode | "";
  address: string;
  name: string;
  description: string;
  unit: string;
  kind: PointKind;
  step: boolean;
  low: number | null;
  high: number | null;
  // Where the range comes from (D2): the server's, a person's, suggested from the first day, or none yet.
  range_origin?: "source" | "edited" | "suggested" | "";
  // What sets this derived point's retention and compression (e.g. "link:<schedule>"); empty: people.
  managed_by?: string;
  // A runs point: how many runs it keeps.
  keep_runs?: number | null;
  // In effect (own, else the source's, else the general settings).
  scan_seconds: number;
  deviation: number;
  // A number point that inherits its deviation with no known range: the share of its value
  // it is compressed to (deviation is then 0); else null.
  deviation_percent: number | null;
  // The exception before the compression, in engineering units, or a share of the value.
  exception: number;
  exception_percent: number | null;
  profile: Profile;
  max_seconds: number;
  // Lines only: the least time between archived values (null or 0: none).
  min_seconds?: number | null;
  retention_days: number;
  // The point's own values (null where it inherits) and where each value in effect comes from.
  own: Record<PointSetting, number | null>;
  origins: Record<PointSetting, Origin>;
  enabled: boolean;
  status: string;
  detail: string;
  // Typed by kind: a number, text, true/false, an ISO time or a JSON object or array.
  value: number | string | boolean | object | null;
  at: number | null;
  reads: number;
  archived: number;
  stored_values: number;
  // Values written for the last 24 hours (counted by the hour of their time).
  stored_day: number;
  stored_bytes: number;
  first: number | null;
  // Whether the source tells the quality of its values (else every value counts as good).
  quality_reported?: boolean;
};

export type Settings = {
  retention_days: number;
  hourly_retention_days: number;
  daily_retention_days: number;
  monthly_retention_days: number;
  default_scan_seconds: number;
  default_deviation_percent: number;
  default_max_seconds: number;
  default_exception_percent: number;
};

/** How fast the archive grows and when the disk fills (D4); days_to_full null: it never fills, or the free disk is unknown. */
export type Forecast = { bytes_per_day: number; bytes_per_year: number; free_bytes: number | null; days_to_full: number | null; alert_days: number; at: number };

export type Overview = {
  points: number;
  sources: number;
  statuses: Record<string, number>;
  collector: { running: boolean; mode: string; heartbeat: number | null; started: number | null; reads_per_second: number; sources: Record<string, SourceState> };
  archive: { values: number; day: number; bytes: number; file_bytes: number; bytes_per_value: number | null; oldest: number | null; forecast?: Forecast };
  compression: { reads: number; archived: number; ratio: number | null };
  settings: Settings;
};

export type Variable = {
  address: string;
  tag: string;
  name: string;
  path: string;
  kind: "number" | "text";
  step?: boolean;
  unit: string;
  description: string;
  low: number | null;
  high: number | null;
};

export type RequestAnswer<T> = { id: number; kind: string; status: "pending" | "ok" | "error"; result?: T & { detail?: string } };

/** Where a point's quality changed: it holds from `t` to the next change (good when none). */
export type QualityChange = { t: string; quality: "good" | "uncertain" | "substituted" | "bad" };
export type Series = { signal: string; kind: string; t: string[]; v: (number | string | boolean | object | null)[]; quality?: QualityChange[]; low?: (number | null)[]; high?: (number | null)[] };

export type AppMeta = { app?: { version?: string } };

/** One asset of PlantCraft's tree as Export offers it (``GET /api/export/options``). */
export interface ExportAsset { id: string; name: string; kind: string; kind_label: string; parent_id: string | null; depth: number; loop: boolean; loops: number; signals: number; missing: number }
export interface ExportOptions { assets: ExportAsset[]; assets_error: string | null; points: number; max_days: number; max_raw_days: number; max_signals: number }
/** What a choice exports (``POST /api/export/preview``). */
export interface ExportPreview { signals: number; assets: number; loops: number; missing: number; tags: string[] }

/** A problem a CSV check found: what, how many lines, and the first of them (line 1 is the header). */
export type ImportProblem = { message: string; count: number; lines: number[]; tags?: string[] };
/** What a CSV file holds (``POST /api/imports/check``); nothing is written by a check. */
export type ImportReport = {
  shape: "wide" | "long" | ""; delimiter: string; decimal: string; times: string; rows: number; values: number;
  start_ms: number | null; end_ms: number | null; tags: { tag: string; kind: "number" | "text"; values: number }[];
  errors: ImportProblem[]; warnings: ImportProblem[];
  // How the file was read (every detected setting filled in), its columns and Excel's sheets.
  options: ReadOptions & { format?: "csv" | "excel"; columns?: string[]; sheets?: string[] };
  // The first lines as read, with each line's time in UTC (null: not readable).
  preview: { columns?: string[]; rows?: string[][]; times?: (string | null)[] };
};
/** How an import reads its file (``csv_table.ReadOptions``); empty or "auto": detected. */
export type ReadOptions = {
  delimiter: "" | "," | ";" | "\t" | "|"; decimal: "" | "." | ","; skip_rows: number; shape: "auto" | "wide" | "long";
  time_column: string; time_format: string; day_first: "auto" | "day" | "month";
  tag_column: string; value_column: string; quality_column: string; tag_prefix: string; sheet: string;
};
export const READ_KEYS: (keyof ReadOptions)[] = ["delimiter", "decimal", "skip_rows", "shape", "time_column", "time_format", "day_first", "tag_column", "value_column", "quality_column", "tag_prefix", "sheet"];
/** One file brought into an import. */
export type ImportRun = { at: number; by: string; file_name: string; bytes: number; rows: number; values: number; start_ms: number | null; end_ms: number | null; warnings: number };
export type ImportCheck = { token: string; file_name: string; bytes: number; timezone: string; ok: boolean; report: ImportReport };
/** An import (``GET /api/imports``): a CSV file loaded once, its values written by the collector. */
export type ImportItem = {
  id: string; name: string; points: number; created: string; status: "writing" | "done" | "error" | "gone"; detail: string; written: number | null;
  file_name: string; bytes: number; shape: string; timezone: string; rows: number; values: number; start_ms: number | null; end_ms: number | null; imported_by: string; warnings: number;
  // How its files are read (the next file is read the same way) and each file, newest first.
  read?: Partial<ReadOptions> & { timezone?: string }; runs?: ImportRun[];
  // While written: the step and the share of its signals done (null while the file is read);
  // queued: waiting for the collector, so it can still be cancelled.
  step?: string; progress?: number | null; queued?: boolean;
  // The folder it repeats from (empty: only people add its files), and its last check.
  repeat?: ImportRepeat | Record<string, never>;
};

export type ImportRepeat = { pattern: string; check_minutes: number; by: string; checked_ms: number | null; files: number; problem: string };

/** The disk one retention takes (H9): raw values or a rollup level, now and at full retention. */
export type RetentionLevel = { level: "raw" | "hour" | "day" | "month"; days: number; now: number; full: number; per_year: boolean };
