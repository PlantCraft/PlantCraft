import { describe, expect, it } from "vitest";
import { forecastText } from "./operationsApi";

describe("disk forecast", () => {
  const size = (bytes: number) => `${Math.round(bytes / 2 ** 30)} GB`;
  it("says in how many days the disk fills", () => {
    expect(forecastText({ bytes_per_day: 2 * 2 ** 30, days_left: 17.6, hours: 48 }, size)).toBe("Fills in about 18 days (2 GB a day)");
    expect(forecastText({ bytes_per_day: 0, days_left: null, hours: 48 }, size)).toBe("Not filling up");
    expect(forecastText(null, size)).toBe("");
  });
});
