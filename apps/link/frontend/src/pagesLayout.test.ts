import { describe, expect, it } from "vitest";
import { chosenLibrary } from "./BlocksPage";
import { NAV } from "./pages";

describe("pages", () => {
  it("opens Blocks on the library in the address, else the first", () => {
    const libraries = [{ library: "input" }, { library: "cpm" }];
    expect(chosenLibrary(libraries, "?library=cpm")).toBe("cpm");
    expect(chosenLibrary(libraries, "?library=nope")).toBe("input");
    expect(chosenLibrary([], "")).toBe("");
  });

  it("orders the menu as the work goes, with one Executions page and no Results nor Assistant entry", () => {
    expect(NAV.map((item) => item.to)).toEqual(["/", "/blocks", "/algorithms", "/schedules", "/executions"]);
    const executions = NAV[4];
    expect(["/executions/round-cpm/fic-101", "/results", "/runs/1", "/assets/x"].every((path) => executions.match(path))).toBe(true);
  });
});
