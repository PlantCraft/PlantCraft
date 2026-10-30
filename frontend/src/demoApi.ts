/** A public demo's visits (api/routers/demo.py): entering, the line, the visit's signs of life. */
import { requestJson } from "./api";
import { t } from "./i18n";
import type { SessionInfo } from "./types";

export interface PublicDemoInfo { seats: number; minutes: number; contact_url?: string }
export interface DemoVisitInfo { seconds_left: number; minutes: number }
export type Entered = SessionInfo & { entered: true };
export type Waiting = { entered: false; ticket: string | null; position: number; wait_seconds: number; seats: number };

export const demoApi = {
  /** `guide`: the role the visitor picked (kept in the visit's audit entry). */
  enter: (ticket: string | null, guide: string | null = null) => requestJson<Entered | Waiting>("/api/demo/enter", { method: "POST", body: JSON.stringify({ ticket, guide }) }),
  heartbeat: (active: boolean, pages: string[] = []) => requestJson<DemoVisitInfo>("/api/demo/heartbeat", { method: "POST", body: JSON.stringify({ active, pages }) }),
};

/** "12:05": minutes and seconds left. */
export function clockText(seconds: number) {
  const left = Math.max(Math.floor(seconds), 0);
  return `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
}

/** "about 4 min" (never "0 min"). */
export function waitText(seconds: number) {
  const minutes = Math.max(Math.ceil(seconds / 60), 1);
  return t("about {minutes} min", { minutes });
}

