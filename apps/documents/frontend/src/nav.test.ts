import { describe, expect, it } from "vitest";
import { appPath, href } from "./nav";
import { t } from "./i18n";

describe("base path", () => {
  it("prefixes app paths with /doc and strips it back", () => {
    expect(href("/d/abc")).toBe("/doc/d/abc");
    expect(href("share/x")).toBe("/doc/share/x");
    expect(appPath("/doc/d/abc")).toBe("/d/abc");
    expect(appPath("/doc/")).toBe("/");
    expect(appPath("/doc")).toBe("/");
  });
});

describe("t()", () => {
  it("fills named fields and leaves unknown ones", () => {
    expect(t("{count} loops", { count: 3 })).toBe("3 loops");
    expect(t("{a} and {b}", { a: "x" })).toBe("x and {b}");
  });
});
