import { describe, expect, it } from "vitest";
import { ago, formatBytes, formatValue } from "./format";

describe("formatting", () => {
  it("writes sizes in binary units", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(3 * 1024 ** 3)).toBe("3 GB");
  });
  it("writes ages", () => {
    expect(ago(1000, 6000)).toBe("5 s ago");
    expect(ago(0, 7_200_000)).toBe("2 h ago");
    expect(ago(null)).toBe("—");
  });
  it("writes values with their unit, text as is", () => {
    expect(formatValue(12.3456, "degC")).toBe("12.35 degC");
    expect(formatValue("AUTO")).toBe("AUTO");
    expect(formatValue(null)).toBe("—");
  });
});
