import { describe, expect, it } from "vitest";
import { appPath, href } from "./nav";
import { t } from "./i18n";

describe("base path", () => {
  it("prefixes app paths with /link and strips it back", () => {
    expect(href("/loops/fic-101")).toBe("/link/loops/fic-101");
    expect(href("algorithms")).toBe("/link/algorithms");
    expect(appPath("/link/loops/fic-101")).toBe("/loops/fic-101");
    expect(appPath("/link/")).toBe("/");
    expect(appPath("/link")).toBe("/");
  });
});

describe("t()", () => {
  it("fills named fields and leaves unknown ones", () => {
    expect(t("{count} loops", { count: 3 })).toBe("3 loops");
    expect(t("{a} and {b}", { a: "x" })).toBe("x and {b}");
  });
});
