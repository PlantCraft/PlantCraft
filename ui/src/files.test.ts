import { describe, expect, it } from "vitest";
import { fillText } from "./files";

describe("fillText", () => {
  it("fills known fields and leaves the rest as written", () => {
    expect(fillText("{count} of {total} points", { count: 3, total: 10 })).toBe("3 of 10 points");
    expect(fillText("{count} of {unknown}", { count: 1 })).toBe("1 of {unknown}");
    expect(fillText("No fields")).toBe("No fields");
  });
});
