/** Settings › Compute (admins): the compute workers and what they run; see docs/compute.md. */
import { requestJson } from "./api";

export interface ComputeExecutor { app: string; environment?: string; version: string | null; slots?: number; free?: number }
export interface ComputeWorker {
  id: string;
  name: string;
  labels: string[];
  state: "pending" | "active" | "paused" | "revoked";
  status: "pending" | "expired" | "active" | "paused" | "offline" | "revoked";
  online: boolean;
  host: string;
  executors: ComputeExecutor[];
  stats: { cpus?: number; load?: number; memory_mb?: number; memory_used_mb?: number };
  /** The largest task size its machine has room for (docs/compute.md). */
  largest_size?: "small" | "medium" | "large";
  created_by: string;
  created_at: string;
  enrolled_at: string | null;
  last_seen_at: string | null;
  enroll_expires_at: string | null;
  running: number;
  done_24h: number;
  failed_24h: number;
}
export interface ComputeQueueRow { app: string; priority: string; queued: number; running: number; done_24h: number; failed_24h: number; oldest_queued_at: string | null; average_seconds: number | null }
export interface ComputeLimits { timeout_seconds: number | null; memory_mb: number | null; updated_by: string; updated_at: string }
export interface ComputeOverview {
  workers: ComputeWorker[];
  queue: ComputeQueueRow[];
  limits: Record<string, ComputeLimits>;
  waiting_without_worker: { app: string; version: string | null; environment?: string; size?: string; queued: number; oldest_queued_at: string }[];
  apps: { id: string; name: string }[];
}
export interface ComputeEnrollment { worker: ComputeWorker; code: string; expires_minutes: number; platform_url: string; command: string }

const worker = (id: string, action: string) => requestJson<ComputeWorker>(`/api/compute/workers/${encodeURIComponent(id)}/${action}`, { method: "POST" });

export const computeApi = {
  overview: () => requestJson<ComputeOverview>("/api/compute"),
  addWorker: (name: string, labels: string[]) => requestJson<ComputeEnrollment>("/api/compute/workers", { method: "POST", body: JSON.stringify({ name, labels }) }),
  newCode: (id: string) => requestJson<ComputeEnrollment>(`/api/compute/workers/${encodeURIComponent(id)}/code`, { method: "POST" }),
  pause: (id: string) => worker(id, "pause"),
  resume: (id: string) => worker(id, "resume"),
  revoke: (id: string) => worker(id, "revoke"),
  remove: (id: string) => requestJson<{ removed: boolean }>(`/api/compute/workers/${encodeURIComponent(id)}`, { method: "DELETE" }),
  setLimits: (app: string, timeout_seconds: number | null, memory_mb: number | null) => requestJson<ComputeLimits>(`/api/compute/limits/${encodeURIComponent(app)}`, { method: "PUT", body: JSON.stringify({ timeout_seconds, memory_mb }) }),
};
