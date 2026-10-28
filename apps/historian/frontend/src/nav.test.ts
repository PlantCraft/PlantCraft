import { describe, expect, it } from "vitest";
import { appPath, href } from "./nav";
import { t } from "./i18n";

describe("base path", () => {
  it("prefixes app paths with /hist and strips it back", () => {
    expect(href("/points/TI-100.PV")).toBe("/hist/points/TI-100.PV");
    expect(href("sources")).toBe("/hist/sources");
    expect(appPath("/hist/points/TI-100.PV")).toBe("/points/TI-100.PV");
    expect(appPath("/hist/")).toBe("/");
    expect(appPath("/hist")).toBe("/");
  });
});

describe("t()", () => {
  it("fills named fields and leaves unknown ones", () => {
    expect(t("{count} loops", { count: 3 })).toBe("3 loops");
    expect(t("{a} and {b}", { a: "x" })).toBe("x and {b}");
  });
});
