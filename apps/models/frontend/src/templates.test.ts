import { describe, expect, it } from "vitest";
import { classPath, classText, placeable, RESTRICTIONS, templatesFor, withOrder } from "./templates";
import { lastSolver, SOLVERS } from "./RunDialogs";

describe("new classes", () => {
  it("writes each specialization and template as one class with the chosen name", () => {
    for (const restriction of RESTRICTIONS.filter((item) => item !== "type")) {
      for (const template of templatesFor(restriction)) {
        const text = classText({ name: "Tank1", restriction, template: template.id }) ?? "";
        expect(text.startsWith(`${restriction} Tank1`)).toBe(true);
        expect(text.trimEnd().endsWith("end Tank1;")).toBe(true);
      }
    }
    expect(classText({ name: "1bad", restriction: "model" })).toBeNull();
    expect(classText({ name: "Fine", restriction: "nope" })).toBeNull();
    expect(classText({ name: "Fine", restriction: "connector", template: "thermal" })).toBeNull();
    expect(classText({ name: "Fine", restriction: "model", extends: "not a name" })).toBeNull();
  });

  it("writes the description, base class, package and partial as OpenModelica does", () => {
    expect(classText({ name: "Drum", restriction: "model", comment: 'Steam "drum"', extends: "P.Base", within: "P", partial: true }))
      .toBe('within P;\npartial model Drum "Steam \\"drum\\""\n  extends P.Base;\nend Drum;\n');
    expect(classText({ name: "Level", restriction: "type", extends: "Modelica.Units.SI.Length" })).toBe("type Level = Modelica.Units.SI.Length;\n");
  });

  it("gives components connectors and an icon, and a system an experiment", () => {
    expect(classText({ name: "Lag", restriction: "block", template: "signal-block" })).toMatch(/RealInput u[\s\S]*RealOutput y[\s\S]*Icon\(/);
    expect(classText({ name: "Wall", restriction: "model", template: "thermal" })).toContain("HeatPort_a port");
    expect(classText({ name: "Heater", restriction: "model", template: "electrical" })).toContain("extends Modelica.Electrical.Analog.Interfaces.OnePort");
    expect(classText({ name: "Plant", restriction: "model", template: "system" })).toContain("experiment(StartTime = 0, StopTime = 10");
  });

  it("puts a class of a package beside its package.mo and lists it in package.order", () => {
    expect(classPath("Drum", "Boiler/package.mo")).toBe("Boiler/Drum.mo");
    expect(classPath("Drum", undefined)).toBe("Drum.mo");
    expect(withOrder("Tank\nValve\n", "Drum")).toBe("Tank\nValve\nDrum\n");
    expect(withOrder("Tank\nDrum\n", "Drum")).toBe("Tank\nDrum\n");
  });

  it("lets models and blocks of the project be dropped into another class", () => {
    expect(placeable({ name: "P.Tank", restriction: "model", partial: false }, "P.Plant")).toBe(true);
    expect(placeable({ name: "P.Plant", restriction: "model", partial: false }, "P.Plant")).toBe(false);
    expect(placeable({ name: "P.Base", restriction: "model", partial: true }, "P.Plant")).toBe(false);
    expect(placeable({ name: "P.Port", restriction: "connector", partial: false }, "P.Plant")).toBe(false);
  });
});

describe("the integrator", () => {
  it("offers omc's solvers with DASSL first and remembers none by default", () => {
    expect(SOLVERS[0].id).toBe("dassl");
    expect(new Set(SOLVERS.map((item) => item.id)).size).toBe(SOLVERS.length);
    expect(lastSolver("Never.Used")).toBe("dassl");
  });
});
