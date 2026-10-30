/** The Operations page API (/api/operations, administrators only); see docs/operations.md. */
import { requestJson } from "./api";
import { t } from "./i18n";

export interface Backup {
  name: string; state: string; reason: string; created_at?: string; size?: number | null;
  suite_version?: string | null; versions?: Record<string, string>; problems?: string[];
  drill?: { state: string; at: string; seconds: number; problems: string[] };
  /** The Historian database's base backup: full, or incremental on ``base`` (``chain``: full first). */
  histcraft_db?: { kind: "full" | "incremental" | string; base?: string | null; chain?: string[]; size?: number; database_bytes?: number; why_full?: string } | null;
  /** Newer backups whose Historian database builds on this one. */
  needed_by?: string[];
}
export interface Operation { action: string; name?: string; phase?: string; state?: string; message?: string; started_at?: string; finished_at?: string; from?: string; to?: string; seconds?: number }
export interface Schedule { enabled: boolean; daily_at: string; timezone: string; drill: boolean; drill_weekday: number; drill_at: string }
export interface OperationsOverview {
  running: Operation | null;
  backups: Backup[];
  free_bytes: number | null;
  history: Operation[];
  drill: { name: string; state: string; at: string; seconds: number; problems: string[] } | null;
  update: { from?: string; to?: string; state: string; message?: string; at?: string } | null;
  release: { version: string; notes: string; release: { upgrade_from?: string; created?: string; components?: Record<string, { name: string; version: string }> } | null } | null;
  schedule: Schedule & { state: { last_daily?: string; last_drill?: string } };
  installer: { online: boolean; last_seen: string | null };
}
export interface ServiceMetrics { service: string; name?: string; state: string; health: string; exit_code?: number | null; status?: string; restarts?: number | null; started_at?: string | null; cpu_pct?: number | null; mem_bytes?: number | null; mem_limit_bytes?: number | null; mem_pct?: number | null }
export interface Incident { incident_id: number; check_key: string; subject: string; detail: string; opened_at: string; closed_at: string | null; notified: number }
export interface SuiteHealth {
  at: string | null;
  watching?: boolean;
  held: boolean;
  checks: { key: string; subject: string; bad: boolean; detail: string }[];
  open: Incident[];
  recent: Incident[];
  metrics: { at: string; services: ServiceMetrics[]; disk: { total_bytes: number; free_bytes: number; free_pct: number | null } | null; error: string | null } | null;
  conversation_id: number | null;
  /** How fast the disk fills (a line through a week of hourly samples); null for the first day. */
  disk_forecast?: DiskForecast | null;
  /** The suite's HTTPS and the Historian's OPC UA certificates, with when they expire. */
  certificates?: Certificate[];
}
export interface Certificate {
  id: string; name: string; use: "https" | "https-local" | "opcua-client" | "opcua-server-pinned" | string;
  source_id?: string | null; subject?: string; issuer?: string; not_after: string | null; fingerprint_sha256?: string;
  days_left: number | null; state: "ok" | "expiring" | "expired" | "auto" | "unknown"; error?: string;
  /** After a renewal: the new certificate, for the OPC UA servers to trust. */
  pem?: string;
}
export interface DiskForecast { bytes_per_day: number; days_left: number | null; hours: number }

/** "Fills in about 18 days (2.1 GB a day)", "Not filling up", or "" before a day of samples. */
export function forecastText(forecast: DiskForecast | null | undefined, size: (bytes: number) => string): string {
  if (!forecast) return "";
  if (forecast.days_left == null) return t("Not filling up");
  return t("Fills in about {days} days ({size} a day)", { days: Math.max(1, Math.round(forecast.days_left)), size: size(forecast.bytes_per_day) });
}
/** Health for everyone: whether each part of the suite runs. */
export interface SuiteStatus { at?: string | null; watching: boolean; held: boolean; services: ServiceMetrics[]; open: Array<{ incident_id: number; subject: string; detail: string; opened_at: string }> }
export interface Queued { request_id: string; action: string; name: string | null; state: string }

const post = (body: unknown = {}): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

export const operationsApi = {
  overview: () => requestJson<OperationsOverview>("/api/operations"),
  health: () => requestJson<SuiteHealth>("/api/operations/health"),
  status: () => requestJson<SuiteStatus>("/api/operations/status"),
  renewCertificate: (id: string) => requestJson<Certificate>(`/api/operations/certificates/${encodeURIComponent(id)}/renew`, post()),
  start: (action: "backup" | "verify" | "drill" | "prune", name?: string) => requestJson<Queued>(`/api/operations/${action}`, post(name ? { name } : {})),
  restore: (name: string, typedName: string, password: string) => requestJson<Queued>("/api/operations/restore", post({ name, typed_name: typedName, password })),
  diagnostics: () => requestJson<Queued>("/api/operations/diagnostics", post()),
  outcome: (requestId: string) => requestJson<{ request_id: string; state: string; message?: string; file?: string; size?: number }>(`/api/operations/requests/${encodeURIComponent(requestId)}`),
  diagnosticsUrl: (requestId: string) => `/api/operations/diagnostics/${encodeURIComponent(requestId)}`,
  schedule: (value: Partial<Schedule>) => requestJson<Schedule>("/api/operations/schedule", { method: "PUT", body: JSON.stringify(value) }),
};
