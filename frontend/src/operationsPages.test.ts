import { describe, expect, it } from "vitest";
import { levelClass, logsCsv, serviceName } from "./OperationsLogs";
import { limitsSummary } from "./OperationsLimits";
import { loadLevel } from "./OperationsPage";
import type { LoadLimits, LogRecord } from "./operationsApi";

const LIMITS: LoadLimits = { enabled: true, cpu_warning: 80, cpu_critical: 95, memory_warning: 80, memory_critical: 95, errors_warning: 2, errors_critical: 5, minutes: 5 };

describe("Operations", () => {
  it("colours a load by the watch's levels", () => {
    expect(loadLevel(79.9)).toBe("");
    expect(loadLevel(80)).toBe("warning");
    expect(loadLevel(97)).toBe("critical");
    expect(loadLevel(72, { warning: 70, critical: 90 })).toBe("warning");
    expect(loadLevel(null)).toBe("");
  });
  it("says how the levels apply, or that they are off", () => {
    expect(limitsSummary(LIMITS)).toContain("5 minutes");
    expect(limitsSummary({ ...LIMITS, enabled: false })).toContain("off");
  });
  it("names the servers and marks the levels", () => {
    expect(serviceName("histcraft")).toBe("Historian");
    expect(serviceName("acme-wiki")).toBe("acme-wiki");
    expect(levelClass("ERROR")).toContain("error");
    expect(levelClass("WARNING")).toContain("warning");
    expect(levelClass("INFO")).toBe("ops-level");
  });
  it("exports the records as CSV, quoting what needs it", () => {
    const records: LogRecord[] = [
      { time: "2026-10-31T03:10:04.000+00:00", service: "modelcraft", level: "ERROR", logger: "modelcraft.study", message: 'worker killed, "exit 137"', request_id: "a91f", error: "Traceback\nMemoryError" },
    ];
    const csv = logsCsv(records).split("\n");
    expect(csv[0]).toBe("time,service,level,logger,message,request_id,error");
    expect(csv[1]).toBe('2026-10-31T03:10:04.000+00:00,modelcraft,ERROR,modelcraft.study,"worker killed, ""exit 137""",a91f,"Traceback');
  });
});

describe("Operations › Requests and Partners", async () => {
  const { answerTime, askUrl, readAskPrefill } = await import("./OperationsRequests");
  const { companyState, hoursCsv } = await import("./OperationsPartners");
  const { hoursText } = await import("./actionsBoard");
  const { recordText } = await import("./OperationsLogs");
  it("times the first answer, or the wait", () => {
    const asked = "2026-10-31T10:00:00Z";
    expect(answerTime({ created_at: asked, first_response_at: "2026-10-31T10:12:00Z" })).toEqual({ text: "12 min", waiting: false });
    expect(answerTime({ created_at: asked, first_response_at: null }, Date.parse("2026-10-31T13:00:00Z"))).toEqual({ text: "3 h", waiting: true });
    expect(answerTime({ created_at: asked, first_response_at: null }, Date.parse("2026-11-04T10:00:00Z")).text).toBe("4 days");
  });
  it("fills the request form from the address, and back", () => {
    expect(readAskPrefill("")).toBeNull();
    const prefill = readAskPrefill("?new=1&from=Analytics&page=%2Fruns%2F7");
    expect(prefill?.text).toContain("Analytics · /runs/7");
    const url = askUrl({ title: "Historian: down", text: "since 9 h", category: "error" });
    const back = readAskPrefill(url.slice(url.indexOf("?")));
    expect(back).toEqual({ title: "Historian: down", text: "since 9 h", category: "error" });
  });
  it("reads hours as people do", () => {
    expect(hoursText(0.75)).toBe("45 min");
    expect(hoursText(1.5)).toBe("1.5 h");
  });
  it("says until when a company has access", () => {
    expect(companyState({ state: "open", access_until: null })).toEqual({ text: "No end date", tone: "" });
    expect(companyState({ state: "ended", access_until: "2026-10-01" }).tone).toBe("bad");
    expect(companyState({ state: "ending", access_until: "2026-11-10" }).text).toContain("Access ends");
  });
  it("exports the month's time with the company, or the plant", () => {
    const csv = hoursCsv([
      { entry_id: 1, action_id: 7, title: "Commission, OPC UA", kind: "request", category: "change", group_id: "acme", username: "ana", display_name: "Ana", day: "2026-10-30", hours: 3, note: "", billable: true, created_at: "", company_id: "acme", company_name: "Acme" },
      { entry_id: 2, action_id: 8, title: "Reset", kind: "request", category: "access", group_id: null, username: "it", display_name: "IT", day: "2026-10-31", hours: 0.5, note: "call", billable: false, created_at: "", company_id: null, company_name: null },
    ]);
    expect(csv.split("\n")[1]).toBe('2026-10-30,Acme,Ana,7,"Commission, OPC UA",3,yes,');
    expect(csv.split("\n")[2]).toBe("2026-10-31,Plant,IT,8,Reset,0.5,no,call");
  });
  it("turns a log record into a request's text", () => {
    const text = recordText({ time: "2026-10-31T10:00:00Z", level: "ERROR", service: "histcraft", logger: "x", message: "write failed", request_id: "abc", error: "Traceback\nValueError: bad" } as LogRecord);
    expect(text).toContain("Historian · ERROR");
    expect(text).toContain("request id: abc");
    expect(text).toContain("ValueError: bad");
  });
});
