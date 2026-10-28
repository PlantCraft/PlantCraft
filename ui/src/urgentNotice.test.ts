import { describe, expect, it } from "vitest";
import { urgentFrom } from "./Inbox.js";
import { markUrgentSeen, runNoticeAction, urgentDue } from "./UrgentNotice.js";

const answer = (status: number, body: unknown) => (async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })) as unknown as typeof fetch;

describe("urgent notifications (docs/quick-access.md)", () => {
  it("keeps only buttons that stay in the suite, and says which run a call", () => {
    const notice = urgentFrom({
      key: "notice:alarmcraft:alarm:12:1:7",
      title: "FIC-1003 flow low",
      priority: "critical",
      href: "https://elsewhere.test/",
      actions: [
        { label: "Acknowledge", href: "/alarm/api/alarms/12/ack", method: "POST" },
        { label: "Away", href: "//elsewhere.test/x" },
        { label: "Open the rule", href: "/alarm/rules/4" },
      ],
    });
    expect(notice?.href).toBeNull();
    expect(notice?.actions).toEqual([
      { label: "Acknowledge", href: "/alarm/api/alarms/12/ack", method: "POST" },
      { label: "Open the rule", href: "/alarm/rules/4", method: "GET" },
    ]);
    expect(urgentFrom(null)).toBeNull();
    expect(urgentFrom({ title: "no key" })).toBeNull();
  });

  it("pops up once per tab", () => {
    const notice = urgentFrom({ key: "k-1", title: "x", actions: [] });
    expect(urgentDue(notice)).toBe(true);
    markUrgentSeen("k-1");
    expect(urgentDue(notice)).toBe(false);
  });

  it("runs a button's call and says what the app answered", async () => {
    expect(await runNoticeAction("/alarm/api/alarms/12/ack", answer(200, { ok: true }))).toEqual({ ok: true, message: "Done" });
    expect(await runNoticeAction("/alarm/api/alarms/12/ack", answer(403, { detail: "Only operators acknowledge." }))).toEqual({ ok: false, message: "Only operators acknowledge." });
    const down = (async () => { throw new Error("offline"); }) as unknown as typeof fetch;
    expect((await runNoticeAction("/alarm/api/alarms/12/ack", down)).ok).toBe(false);
  });
});
