import { describe, expect, it } from "vitest";
import { safeLink } from "./executionsApi";

describe("safeLink", () => {
  it("keeps paths on this origin and http(s) addresses", () => {
    expect(safeLink("/cpm/runs/1")).toEqual({ href: "/cpm/runs/1", external: false });
    expect(safeLink("https://other.test/r")).toEqual({ href: "https://other.test/r", external: true });
  });
  it("drops anything else", () => {
    for (const url of [null, "", "//evil.test/x", "/a\\b", "javascript:alert(1)", "ftp://x.test/", "runs/1"]) expect(safeLink(url)).toBeNull();
  });
});
