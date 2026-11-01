/** A public demo's visits (api/routers/demo.py): entering, the line, the visit's signs of life. */
import { requestJson } from "./api";
import { t } from "./i18n";
import type { SessionInfo } from "./types";

/** `updating`: an update is announced or under way (no new visit starts); `updating_url`: where a
 * visit waits for it (the site's page). */
export interface PublicDemoInfo { seats: number; minutes: number; contact_url?: string; updating_url?: string; updating?: boolean }
/** `clock_seconds`: the visit's clock, shown all the time; `seconds_left`: when it ends (the clock,
 * or sooner once the visitor stops using it for `idle_minutes`); `update_seconds`: until an
 * announced update ends every visit (null: none). */
export interface DemoVisitInfo { update_seconds?: number | null; clock_seconds: number; seconds_left: number; minutes: number; idle_minutes: number }
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

