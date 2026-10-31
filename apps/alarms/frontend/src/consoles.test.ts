import { describe, expect, it } from "vitest";
import { consolesProblem, homeConsole, newConsoleId } from "./consoles";
import type { Console, ConsoleLoad } from "./types";

const board = (id: string, name: string, areas: string[] = ["U-100"]): Console => ({ id, name, areas, operators: [], per_hour: null });

describe("consoles", () => {
  it("names a new console after the first free number", () => {
    expect(newConsoleId([])).toBe("console-1");
    expect(newConsoleId([board("console-2", "B")])).toBe("console-3");
    expect(newConsoleId([board("console-3", "A"), board("x", "B")])).toBe("console-4");
  });
  it("says what keeps the consoles from being saved", () => {
    expect(consolesProblem([board("a", "Board 1"), board("b", "Board 2")])).toBe("");
    expect(consolesProblem([board("a", " ")])).toMatch(/name/);
    expect(consolesProblem([board("a", "Board  1"), board("b", "board 1")])).toMatch(/Two consoles/);
    expect(consolesProblem([board("a", "Board 1", [])])).toMatch(/no area/);
  });
  it("opens Performance on the console the person sits at", () => {
    const loads = [{ id: "a", operators: ["ana"] }, { id: "b", operators: ["bo", "operator"] }] as ConsoleLoad[];
    expect(homeConsole(loads, "operator")).toBe("b");
    expect(homeConsole(loads, "engineer")).toBe("");
  });
});
