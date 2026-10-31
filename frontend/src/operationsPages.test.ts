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
