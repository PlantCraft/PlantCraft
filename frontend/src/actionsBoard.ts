/** Pure helpers of the Actions board: columns by status and how long each action has been there. */
import { t } from "./i18n";
import type { Action, Choice } from "./collabApi";

/** The board's columns, in the workflow's order; archived ones (status id "cancelled") only when asked for. */
export const BOARD_STATUSES = ["open", "in_progress", "blocked", "done"] as const;

export interface BoardColumn { id: string; label: string; items: Action[] }

/** Actions per status column: open work by priority then due date, finished work newest first. */
export function boardColumns(items: Action[], statuses: Choice[], showCancelled = false): BoardColumn[] {
  const wanted = showCancelled ? [...BOARD_STATUSES, "cancelled"] : [...BOARD_STATUSES];
  const rank: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
  return wanted.map((id) => {
    const column = items.filter((item) => item.status === id);
    column.sort(id === "done" || id === "cancelled"
      ? (a, b) => (b.completed_at ?? b.updated_at).localeCompare(a.completed_at ?? a.updated_at)
      : (a, b) => (rank[a.priority] ?? 9) - (rank[b.priority] ?? 9) || (a.due_at ?? "9999").localeCompare(b.due_at ?? "9999") || a.created_at.localeCompare(b.created_at));
    return { id, label: statuses.find((item) => item.id === id)?.label ?? id, items: column };
  });
}

/** A span of time in words: "45 min", "5 h", "3 days". */
export function spanText(ms: number): string {
  const minutes = Math.max(0, Math.round(ms / 60_000));
  if (minutes < 60) return t("{count} min", { count: minutes });
  const hours = Math.round(minutes / 60);
  if (hours < 48) return t("{count} h", { count: hours });
  return t("{count} days", { count: Math.round(hours / 24) });
}

/** How long an action has been where it is: open for, in progress for, done in. */
export function timeText(action: Pick<Action, "status" | "created_at" | "updated_at" | "completed_at" | "status_since">, now = Date.now()): string {
  const since = (value: string) => now - new Date(value).getTime();
  if (action.status === "done" && action.completed_at) return t("Done in {span}", { span: spanText(new Date(action.completed_at).getTime() - new Date(action.created_at).getTime()) });
  if (action.status === "open") return t("Open for {span}", { span: spanText(since(action.created_at)) });
  const moved = action.status_since ?? action.updated_at;
  if (action.status === "cancelled") return t("Archived {span} ago", { span: spanText(since(moved)) });
  if (action.status === "blocked") return t("Blocked for {span}", { span: spanText(since(moved)) });
  return t("In progress for {span}", { span: spanText(since(moved)) });
}
