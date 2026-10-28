import { describe, expect, it } from "vitest";
import type { AuditRow } from "./AuditLog";
import { defaultBoard, showsAppWidgets } from "./PlatformHome";
import { actionText, changesWidget, systemWidget, type SystemFacts } from "./SystemWidgets";

const NOW = Date.parse("2026-10-27T15:00:00Z");
const ADMIN: SystemFacts = {
  admin: true, watching: true, open: 0, services: { running: 9, total: 9 }, version: "0.4.0", update: null,
  disk: { free_bytes: 42 * 2 ** 30, free_pct: 35, days_left: null, state: "ok" },
  backup: { name: "20261027-020000-daily", at: "2026-10-27T02:00:00Z", state: "ok" }, signed_in_today: 3,
};

describe("PlantCraft's Overview board", () => {
  it("is the installation's health by default, the audit's changes only for administrators", () => {
    expect(defaultBoard(true).map((item) => [item.widget, item.x, item.y, item.w, item.h])).toEqual([
      ["apps-status", 0, 0, 6, 3], ["historian-status", 6, 0, 6, 3], ["system", 0, 3, 6, 2], ["recent-changes", 6, 3, 6, 2],
    ]);
    expect(defaultBoard(false).map((item) => item.widget)).toEqual(["apps-status", "historian-status", "system"]);
    // No app widget in it: nothing waits for the apps.
    expect(showsAppWidgets(defaultBoard(true))).toBe(false);
    expect(showsAppWidgets(["attention", { i: "x", widget: "linkcraft:worst", x: 0, y: 0, w: 6, h: 3 }])).toBe(true);
    expect(showsAppWidgets(null)).toBe(false);
  });
});

describe("the System card", () => {
  it("shows an administrator the disk, the last backup, the version and who signed in", () => {
    const card = systemWidget(ADMIN, NOW);
    expect(card).toMatchObject({ title: "Healthy", state: "ok", href: "/health" });
    expect(card.facts.map((fact) => fact.label)).toEqual(["Free disk", "Last backup", "Version", "Signed in today"]);
    expect(card.facts[0]).toMatchObject({ value: "42 GB · 35 %", state: "ok" });
    expect(card.facts[3].value).toBe(3);
  });

  it("colours what is wrong and says nothing is there yet", () => {
    const card = systemWidget({ ...ADMIN, open: 2, disk: { ...ADMIN.disk!, state: "alarm" }, backup: { ...ADMIN.backup!, state: "alarm" }, update: { state: "rolled-back" } }, NOW);
    expect(card.state).toBe("alarm");
    expect(card.title).toBe("2 problems open");
    expect(card.facts[0].state).toBe("alarm");
    expect(String(card.facts[1].value)).toMatch(/^Failed /);
    expect(card.facts[2].state).toBe("warning");
    const fresh = systemWidget({ ...ADMIN, services: null, watching: false, disk: null, backup: null }, NOW);
    expect(fresh.facts[0].value).toBe("—");
    expect(fresh.facts[1]).toMatchObject({ value: "None yet", state: null });
    // Nothing open, but a fact in alarm or warning colours the head.
    expect(systemWidget({ ...ADMIN, disk: { ...ADMIN.disk!, state: "alarm" } }, NOW)).toMatchObject({ title: "Needs attention", state: "alarm" });
    expect(systemWidget({ ...ADMIN, backup: { ...ADMIN.backup!, state: "warning" } }, NOW)).toMatchObject({ title: "Worth a look", state: "warning" });
  });

  it("shows anyone else the version and the services", () => {
    const card = systemWidget({ admin: false, watching: true, open: 0, services: { running: 8, total: 9 }, version: "0.4.0", update: null }, NOW);
    expect(card.facts.map((fact) => fact.label)).toEqual(["Version", "Services"]);
    expect(card.facts[1]).toMatchObject({ value: "8 of 9 running", state: "alarm" });
    expect(card.state).toBe("alarm");
  });
});

describe("Recent changes", () => {
  it("lists what changed, who and when, each opening the audit log", () => {
    const rows: AuditRow[] = [
      { audit_id: 2, at: "2026-10-27T14:00:00Z", username: "ana", app_id: "linkcraft", action: "loop.update", subject: "FIC-101", detail: null },
      { audit_id: 1, at: "2026-10-20T09:30:00Z", username: "admin", app_id: "processcraft", action: "users.create", subject: "", detail: null },
    ];
    const list = changesWidget(rows, [{ username: "ana", display_name: "Ana Lima", role: "", active: 1 }], NOW);
    expect(list.items.map((item) => [item.label, item.detail, item.href])).toEqual([
      ["Update loop · FIC-101", "Ana Lima · Analytics", "/setup/audit"],
      ["Create users", "admin", "/setup/audit"],
    ]);
    // Today by the hour, an older change with its day.
    expect(String(list.items[1].value)).toMatch(/Oct/);
    expect(String(list.items[0].value)).not.toMatch(/Oct/);
    expect(changesWidget([], [], NOW).items).toEqual([]);
    expect(actionText("app_key.create")).toBe("Create app key");
    expect(actionText("operations.backup")).toBe("Operations backup");
  });
});
