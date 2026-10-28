import { describe, expect, it } from "vitest";
import { FULL_ACCESS, canSee, safeNext } from "./session";
import type { AccessInfo } from "./types";

const viewer: AccessInfo = { level: "viewer", label: "Leitura", applications: ["data_quality"], can_edit: false, is_admin: false };
const screen: AccessInfo = { level: "dashboards", label: "Só dashboards", applications: null, can_edit: false, is_admin: false };

describe("canSee", () => {
  it("administrators see every section and application", () => {
    expect(canSee(FULL_ACCESS, "users")).toBe(true);
    expect(canSee({ ...FULL_ACCESS, applications: ["cpm"] }, "plant", "data_quality")).toBe(true);
  });
  it("readers see only their applications and no settings", () => {
    expect(canSee(viewer, "plant", "data_quality")).toBe(true);
    expect(canSee(viewer, "plant", "cpm")).toBe(false);
    expect(canSee(viewer, "settings")).toBe(false);
    expect(canSee(viewer, "users")).toBe(false);
  });
  it("dashboards-only people see the dashboards alone", () => {
    expect(canSee(screen, "dashboards")).toBe(true);
    expect(canSee(screen, "plant")).toBe(false);
  });
});

describe("safeNext", () => {
  const origin = "https://plant.example";
  it("returns to a page of this origin after signing in", () => {
    expect(safeNext("?next=/cpm/loops%3Farea%3Dnorth", origin)).toBe("/cpm/loops?area=north");
    expect(safeNext("?next=/cpm/", origin)).toBe("/cpm/");
  });
  it("never sends the browser to another site", () => {
    for (const next of ["//evil.example/x", "https://evil.example/", "/\\evil.example", "javascript:alert(1)", ""]) {
      expect(safeNext(`?next=${encodeURIComponent(next)}`, origin)).toBeNull();
    }
    expect(safeNext("", origin)).toBeNull();
  });
});
