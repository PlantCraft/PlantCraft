import type { Diagram } from "@plantcraft/ui/blockEditor";

export type Creates = "alarm" | "notice";
export type Severity = "warning" | "critical";
export type Priority = "critical" | "high" | "medium" | "low";
export type Discipline = "operations" | "process" | "instrumentation" | "electrical" | "mechanical" | "safety";
export type Status = "unacked" | "rtn_unacked" | "acked" | "shelved" | "out_of_service" | "normal";

export interface Me {
  username: string; name: string; level: string; access: string; role: string; can_edit: boolean; is_admin: boolean;
  processcraft_url: string; version: string; service_key: boolean;
  /** PlantCraft can send email now (Setup, Email): a rule offers it only then. */
  email_ready?: boolean;
  /** A public demo visit (read-only: every change is refused). */
  demo?: { ends: number } | null;
}

/** What one alarm of a rule is about, and the rule in words. */
export interface AlarmDraft {
  name: string; rule_id: string | null; subject: string; asset_id: string | null; label: string | null;
  priority: Priority; creates: Creates; sentence: string; hears: string[]; logic: string;
  cause: string; consequence: string; action: string; enabled: boolean; rule_enabled: boolean;
  owner: string | null; area: string | null; discipline: Discipline | null; notify: boolean;
}

export interface Alarm extends AlarmDraft {
  alarm_id: string; status: Status; condition: string; priority_label: string;
  active: boolean; acked: boolean; acked_at: string | null; acked_by: string | null;
  value: number | null; value_at: string | null; raised_at: string | null; signal: string | null;
  known: boolean | null; reason: string; unit: string; message: string; members_active: string[];
  shelved_until: string | null; shelved_by: string | null;
  shelve_reason: string | null; updated_at: string; updated_by: string; created_by: string | null;
  area_id: string | null; area_name: string | null; area_path: string[]; discipline_label: string;
  /** The person answers for it, is in the answering group, or its rule notifies them. */
  mine?: boolean;
  rule_name?: string | null; last_summary?: string; severity?: string | null; schedule_id?: string | null;
  run?: string | null;
}

export interface MonitorStatus {
  enabled: boolean; running: boolean; cycles: number; cycle_seconds: number; last_cycle: string | null;
  last_error: string; publish_error: string; notify_error?: string;
}

export interface Summary {
  counts: Record<Status | "total" | "active" | "unknown" | "last_24h" | "notices_24h" | "mine", number>;
  alarms: Alarm[]; out_of_service: Alarm[]; monitor: MonitorStatus; at: string;
}

export interface JournalEntry {
  id: number; at: string; alarm_id: string; name: string; priority: string; action: string; by: string;
  value: number | null; detail: string;
}

export interface Occurrence {
  id?: number; alarm_id?: string; started_at?: string; ended_at?: string | null; start?: string; end?: string | null;
  acked_at?: string | null; acked_by?: string | null; peak: number | null; limit?: number | null;
}

export interface Chart { t: string[]; v: number[] }

/** One subject of a tried rule: how often its alarm would have been raised. */
export interface TriedAlarm { label: string; subject: string; signal: string | null; count: number; occurrences: Occurrence[]; unknown: string; message: string }

export interface TryResult {
  signal: string | null; start: string; end: string; step: number; count: number; per_hour: number;
  occurrences: Occurrence[]; chart: Chart; subjects: number; tried: number; messages: number;
  messages_per_hour: number; alarms: TriedAlarm[]; problems: string[]; events?: number;
}

export interface AlarmHistory {
  alarm: Alarm; start: string; end: string; occurrences: Occurrence[]; journal: JournalEntry[]; chart: Chart; problem: string;
  /** An events alarm: the events about its subject its rule counted (or that cleared it). */
  events?: Array<IncomingEvent & { counted: boolean }>;
}

export interface Figure { id: string; label: string; help?: string; value: number; unit?: string; target: string; status: string }

export interface Performance {
  start: string; end: string; window: string; total: number; figures: Figure[];
  per_slot: Array<{ at: string; count: number }>;
  /** Raised per whole hour, by priority (the Overview's rate). */
  hourly: Array<{ at: string; counts: Record<string, number> }>;
  top: Array<{ alarm_id: string; name: string; count: number; share: number; chattering: boolean; priority: string; owner?: string | null }>;
  chattering: Array<{ alarm_id: string; name: string }>; stale: Array<{ alarm_id: string; name: string }>;
  priorities: Array<{ priority: string; share: number; target: number }>;
  mean_ack_seconds: number | null; unacked: number;
  /** EEMUA 191 band from the average and the peak per 10 minutes. */
  eemua: { level: string; average_per_10min: number; peak_per_10min: number; bands: Array<{ level: string; average: number | null; peak: number | null }> };
  /** Floods with hysteresis: start above the flood limit, end below half of it. */
  floods: Array<{ start: string; end: string; minutes: number; alarms: number; peak: number }>;
  flood_minutes: number;
  acknowledge: Array<{ priority: string; count: number; median_seconds: number | null; p90_seconds: number | null }>;
  fleeting: Array<{ alarm_id: string; name: string; count: number; owner?: string | null }>;
}

export interface AssetOption { id: string; name: string; kind: string | null; parent: string | null; signals: Record<string, string> }
export interface SignalOption { id: string; name: string; unit: string; kind: string; low: number | null; high: number | null }
export interface AssetAlarms { asset: { id: string; name: string | null; kind: string | null }; alarms: Alarm[] }

export interface Person { username: string; name: string; role?: string | null; job_title?: string | null; unit?: string | null; groups?: string[] }
export interface Group { id: string; name: string; kind?: string | null; description?: string; asset_id?: string | null; coordinator?: string | null; members: string[] }
export interface Choice { id: string; label: string }
export interface Directory { people: Person[]; groups: Group[]; disciplines: Choice[]; priorities: Choice[] }

export type Day = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";
export interface HoursWindow { days: Day[]; start: string; end: string }
export interface EscalationStep { after_minutes: number; recipients: string[]; email: boolean }
export type HoursMode = "always" | "inside" | "outside";
/** Who hears about a rule's alarms, how and when (``owner``: each alarm's responsible). */
export interface NotifyDraft {
  enabled: boolean; recipients: string[]; email: boolean; group_seconds: number; repeat_minutes: number; notify_cleared: boolean; always_now?: boolean;
  hours_mode: HoursMode; hours: HoursWindow[]; timezone: string; escalations: EscalationStep[];
}
export interface Named { id: string; name: string }

export type Op = ">" | ">=" | "<" | "<=" | "==" | "!=" | "between" | "outside" | "changed" | "unchanged";
/** A value as the Explorer gave it: a signal (``{asset}`` for each asset of the rule) or a role. */
export interface SimpleValue { signal: string; role: string; name: string; unit: string }
/** Events of some kinds about the rule's subject (``subject``), any (``any``) or one ref. */
export interface SimpleEvent { kinds: string[]; severities: Severity[]; about: string; name: string }
export interface SimpleCondition {
  input: "value" | "event"; value: SimpleValue | null; op: Op; limit: number | null; high: number | null; deadband: number;
  event: SimpleEvent | null; test: "open" | "count"; count: number; window_minutes: number; for_seconds: number; for_points: number;
}
/** The Simple form: one to three conditions joined by and (or by or). */
export interface SimpleLogic { conditions: SimpleCondition[]; combine: "and" | "or"; clear_after_seconds: number }

export type Per = "asset" | "execution" | "rule";
/** Where a rule applies: assets, every asset under branches or of types, the assets of
 * executions (``<app>:<id>``), or any asset its events name. Nothing: one alarm on named values. */
export interface Where { assets: string[]; under: string[]; types: string[]; executions: string[]; anywhere: boolean; per: Per }
export type Editor = "simple" | "blocks" | "python";

/** A rule as a person writes it: where, when (its diagram), what it makes, who hears and why. */
export interface RuleDraft {
  name: string; enabled: boolean; creates: Creates; priority: Priority; where: Where;
  editor: Editor; simple: SimpleLogic | null; diagram: Diagram;
  owner: string | null; area: string | null; discipline: Discipline | null; notify: NotifyDraft;
  /** Its alarms colour their assets and show in the Active alarms widgets. */
  dashboards: boolean;
  cause: string; consequence: string; action: string;
}

export interface Rule extends RuleDraft {
  rule_id: string; editor_label: string; priority_label: string; creates_label: string;
  where_words: string; sentence: string; valid: boolean; alarms: number; active: number; unacked: number; unknown: number;
  notifies: boolean; recipients: string[]; updated_at: string; updated_by: string; created_by?: string | null;
  /** On the rule's own page: its alarms, one per subject. */
  alarm_rows?: Alarm[];
}

/** A suite execution a rule may cover (``<app>:<id>``). */
export interface Execution { id: string; app: string; name: string; cadence: string; assets: number }

/** An event another app of the suite reported (PlantCraft's events), with the rules it counted for. */
export interface IncomingEvent {
  id: number; at: string; app: string; kind: string; subject: string; summary: string; severity: string;
  payload: Record<string, unknown>; refs: string[]; rules: string[]; rule_names?: string[];
  phase?: "instant" | "start" | "end"; key?: string; category?: string;
}
/** One event's page: the event, what its app's catalog says about its kind, the other starts and
 * ends of the same condition, and the rules that hear its kind. */
export interface EventDetail {
  event: Omit<IncomingEvent, "id"> & { id: number | null };
  declared: { title: string; description: string; app_name: string } | null;
  history: IncomingEvent[]; open: boolean; kind_rules: Array<{ rule_id: string; name: string }>;
}
/** A condition an app opened and has not ended (a service down). */
export interface Condition { app: string; key: string; kind: string; subject: string; summary: string; severity: string; opened_at: string }
/** One event an app declares in its catalog (app.toml), with the rule it suggests. */
export interface CatalogEvent {
  kind: string; name: string; title: string; description?: string; severity: string; category: string; phase: "instant" | "interval";
  payload?: Record<string, string>; rule?: { when: string; minutes: number; count: number; priority: Priority; creates: string; notify: string; enabled: boolean };
  rules: Array<{ rule_id: string; name: string }>;
}
export interface CatalogApp { app: string; name: string; events: CatalogEvent[]; undeclared: string[]; updated_at: string | null }
export interface Catalog { apps: CatalogApp[]; error: string; service_key: boolean }
export interface Philosophy {
  statement: string; per_person_hour: number; flood_alarms: number; flood_minutes: number;
  immediate: Priority[]; digest: Priority[]; digest_times: string[]; timezone: string;
  chatter_minute: number; chatter_hour: number; stale_hours: number;
  target_high: number; target_medium: number; target_low: number;
}
export interface PhilosophyRecord extends Philosophy { defaults: Philosophy; updated_at: string | null; updated_by: string | null; next_summary: string }
export interface IncomingCount { app: string; kind: string; count: number; last: string; counted: number }
export interface Incoming { events: IncomingEvent[]; counts: IncomingCount[]; window: string; error: string; read: number; service_key: boolean }

export interface Silence {
  silence_id: number; areas: string[]; areas_named: Named[]; disciplines: Discipline[]; alarm_ids: string[];
  starts_at: string; ends_at: string; reason: string; created_by: string; ended_by: string | null; active: boolean;
}
export interface SilenceDraft { areas: string[]; disciplines: Discipline[]; alarm_ids: string[]; minutes: number; reason: string }
export interface OutboxRow {
  id: number; alarm_id: string; name: string; policy_id: string; rule_id: string | null; rule_name: string | null; event: "raised" | "cleared" | "reminder" | "escalation"; priority: Priority;
  at: string; detail: string; recipients: string[]; email: boolean; step: number | null; status: "pending" | "sent" | "dropped" | "held" | "digest" | "chatter";
  sent_at: string | null; delivered: number; error: string;
}
export interface Sent {
  outbox: OutboxRow[]; limited: Array<{ recipient: string; held: number }>; limit_per_hour: number;
  inhibited: number; error: string; service_key: boolean;
}
