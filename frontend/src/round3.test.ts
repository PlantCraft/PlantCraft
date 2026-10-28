import { describe, expect, it } from "vitest";
import { boardColumns, spanText, timeText } from "./actionsBoard";
import { signalRows } from "./AssetRecord";
import { insideCounts, tabOf } from "./AssetsPage";
import type { Action } from "./collabApi";
import { alarmCounts, onlineText } from "./PlatformHome";

const action = (id: number, status: Action["status"], priority: string, extra: Partial<Action> = {}): Action => ({
  action_id: id, title: `A${id}`, description: "", status, status_label: status, priority, priority_label: priority,
  owner: null, owner_name: null, due_at: null, overdue: false, refs: [], created_by: "ana", created_by_name: "Ana",
  created_at: "2026-10-01T10:00:00Z", updated_at: "2026-10-02T10:00:00Z", completed_at: null, ...extra,
});
const STATUSES = [{ id: "open", label: "Open" }, { id: "in_progress", label: "In progress" }, { id: "blocked", label: "Blocked" }, { id: "done", label: "Done" }, { id: "cancelled", label: "Cancelled" }];

describe("the actions board", () => {
  it("puts each action in its status column, most urgent first, finished newest first", () => {
    const items = [action(1, "open", "low"), action(2, "open", "critical"), action(3, "done", "low", { completed_at: "2026-10-03T00:00:00Z" }), action(4, "done", "low", { completed_at: "2026-10-05T00:00:00Z" }), action(5, "cancelled", "low")];
    const columns = boardColumns(items, STATUSES);
    expect(columns.map((column) => column.id)).toEqual(["open", "in_progress", "blocked", "done"]);
    expect(columns[0].items.map((item) => item.action_id)).toEqual([2, 1]);
    expect(columns[3].items.map((item) => item.action_id)).toEqual([4, 3]);
    expect(boardColumns(items, STATUSES, true).at(-1)?.items).toHaveLength(1);
  });

  it("says how long each card has been where it is", () => {
    const now = new Date("2026-10-04T10:00:00Z").getTime();
    expect(spanText(30 * 60_000)).toBe("30 min");
    expect(spanText(5 * 3_600_000)).toBe("5 h");
    expect(timeText(action(1, "open", "low"), now)).toBe("Open for 3 days");
    expect(timeText(action(1, "in_progress", "low", { status_since: "2026-10-04T06:00:00Z" }), now)).toBe("In progress for 4 h");
    expect(timeText(action(1, "done", "low", { completed_at: "2026-10-01T12:00:00Z" }), now)).toBe("Done in 2 h");
  });
});

describe("home", () => {
  it("counts alarms and attention across apps, and what is online", () => {
    expect(alarmCounts({ last_run: null, schedules: 0, findings: { linkcraft: { alarm: 2, warning: 1, total: 9 }, alarmcraft: { alarm: 1, total: 3 } }, actions: { open: 0, overdue: 0, done: 0, total: 0 } })).toEqual({ alarm: 3, warning: 1 });
    expect(onlineText([{ state: "online" }, { state: "offline" }, { state: "off" }])).toBe("1 of 2 online");
  });
});

describe("one asset", () => {
  it("reads its tab from the address", () => {
    expect(tabOf("?tab=signals")).toBe("signals");
    expect(tabOf("?tab=nope")).toBe("overview");
    expect(tabOf("")).toBe("overview");
  });

  it("lists every role, the gaps and the signals in no role", () => {
    const type = { roles: [{ key: "pv", name: "PV", required: true }, { key: "sp", name: "SP", required: true }, { key: "op", name: "OP", required: false }] } as never;
    const signal = (signal_id: string, role: string) => ({ signal_id, role, name: signal_id, unit: "", origin: "map" });
    const rows = signalRows(type, [signal("FI-1", "pv"), signal("TI-9", "temperature")]);
    expect(rows.map((row) => [row.roleName, row.signal?.signal_id ?? null, row.missing])).toEqual([["PV", "FI-1", false], ["SP", null, true], ["OP", null, false], ["temperature", "TI-9", false]]);
  });

  it("counts what is inside it at any depth", () => {
    const items = [{ asset_id: "u1", parent_id: "site", kind: "unit" }, { asset_id: "a1", parent_id: "u1", kind: "area" }, { asset_id: "l1", parent_id: "a1", kind: "loop" }, { asset_id: "l2", parent_id: "a1", kind: "loop" }, { asset_id: "u2", parent_id: "site", kind: "unit" }];
    expect(insideCounts(items, "u1")).toEqual({ area: 1, loop: 2 });
  });
});
