import { describe, expect, it } from "vitest";
import { NAV } from "./pages";

describe("suite frame", () => {
  it("lists the app's pages in the suite's order", () => {
    expect(NAV.map((item) => [item.label, item.to])).toEqual([
      ["Overview", "/"], ["Sources", "/sources"], ["Signals", "/points"], ["Imports", "/imports"], ["Exports", "/exports"], ["Settings", "/settings"],
    ]);
  });
});
