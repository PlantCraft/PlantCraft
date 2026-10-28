import { describe, expect, it } from "vitest";
import { purgeIn } from "./RetiredPoints";

describe("removed points", () => {
  it("says when the history goes for good", () => {
    const now = Date.UTC(2026, 9, 23);
    expect(purgeIn(now + 12 * 86_400_000, now)).toBe("in 12 days");
    expect(purgeIn(now + 3_600_000, now)).toBe("in 1 day");
    expect(purgeIn(now - 1, now)).toBe("today");
  });
});
