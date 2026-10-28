/** API v1 runs and schedules (docs/api-v1.md, "Results, events, runs and schedules"). */
import { requestJson } from "./api";
import { suiteApi } from "./suiteApi";

export type RunStatus = "queued" | "running" | "done" | "failed" | "cancelled";
export const RUN_STATUSES: RunStatus[] = ["queued", "running", "done", "failed", "cancelled"];
export interface Run { app: string; id: string; name: string; status: RunStatus; trigger: "manual" | "schedule" | "api"; started_at: string | null; finished_at: string | null; subjects: string[]; summary: string; url: string | null; updated_at: string }
export interface Schedule { app: string; id: string; name: string; cadence: string; next_run: string | null; enabled: boolean; url: string | null; updated_at: string }

async function v1<T>(path: string): Promise<T> {
  const { token } = await suiteApi.renewToken();
  return requestJson<T>(path, { headers: { Authorization: `Bearer ${token}` } });
}

export const executionsApi = {
  runs: (app: string, status: string) => {
    const params = new URLSearchParams({ limit: "500" });
    if (app) params.set("app", app);
    if (status) params.set("status", status);
    return v1<Run[]>(`/api/v1/runs?${params}`);
  },
  schedules: (app: string) => v1<Schedule[]>(`/api/v1/schedules${app ? `?${new URLSearchParams({ app })}` : ""}`),
};

/** A link into the app: a path on this origin or an http(s) address; anything else is not a link. */
export function safeLink(url: string | null): { href: string; external: boolean } | null {
  if (!url) return null;
  if (url.startsWith("/") && !url.startsWith("//") && !url.includes("\\")) return { href: url, external: false };
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? { href: parsed.href, external: true } : null;
  } catch {
    return null;
  }
}
