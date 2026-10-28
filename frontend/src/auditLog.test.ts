import { describe, expect, it } from "vitest";
import { actionLabel, auditQuery, bucketPeriod, detailText, fillBuckets } from "./AuditLog";

describe("audit log page", () => {
  it("names the sign-in actions and keeps the others as written", () => {
    expect(actionLabel("session.sign_in_failed")).toBe("Sign-in failed");
    expect(actionLabel("asset.update")).toBe("asset.update");
  });
  it("shows the detail in one line", () => {
    expect(detailText({ address: "10.0.0.5", method: "ldap" })).toBe("address 10.0.0.5 · method ldap");
    expect(detailText({ count: 3 })).toBe("count 3");
    expect(detailText(null)).toBe("");
    expect(detailText(["a"])).toBe('["a"]');
  });
  it("asks for the period, the quick filter, the person and the app", () => {
    const now = Date.parse("2026-10-24T12:00:00Z");
    const base = { period: { window: "7d", from: "", to: "" }, kind: "", username: "", appId: "" };
    expect(auditQuery(base, now)).toBe("start=2026-10-17T12%3A00%3A00.000Z");
    expect(auditQuery({ ...base, kind: "failed", username: "vera", appId: "alarmcraft" }, now)).toBe("start=2026-10-17T12%3A00%3A00.000Z&kind=failed&username=vera&app_id=alarmcraft");
  });
  it("zooms into the hour or the day of a bar", () => {
    const hour = bucketPeriod({ at: "2026-10-24T09:00:00Z", total: 3, failed: 0 }, "hour");
    expect(hour.window).toBe("fixed");
    expect(new Date(hour.to).getTime() - new Date(hour.from).getTime()).toBe(3_600_000);
  });
  it("draws every hour of the period, the empty ones too", () => {
    const filled = fillBuckets([{ at: "2026-10-24T10:00:00Z", total: 4, failed: 1 }], "hour", "2026-10-24T07:30:00Z", "2026-10-24T11:10:00Z");
    expect(filled.map((item) => item.total)).toEqual([0, 0, 0, 4, 0]);
    expect(filled[0].at).toBe("2026-10-24T07:00:00.000Z");
  });
});
