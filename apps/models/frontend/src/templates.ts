/**
 * New classes, the way OpenModelica's "New Modelica Class" dialog makes them: a name, a
 * specialization (model, block, connector...), a description, an optional base class, the package
 * it goes in and whether it is partial. Models and blocks can also start from a template (owner,
 * 2026-10-21: "create the blocks, keep them somewhere, connect them into a plant and run it all
 * together"): a component gets connectors and an icon, so it can be dragged from the project into
 * a system's diagram like a library class; a system is the empty diagram where components are
 * connected and simulated.
 */
import { t } from "./i18n";

/** The specializations offered, in OpenModelica's order of use. */
export const RESTRICTIONS = ["model", "block", "connector", "expandable connector", "record", "function", "package", "type", "class"];

export interface Template { id: string; label: string; detail: string; kind: string; comment: string; inner: string }

const ICON = (color: string, label: string) =>
  `  annotation(Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {${color}}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid, radius = 8), Text(extent = {{-90, 40}, {90, -40}}, textString = "${label}", textColor = {${color}}), Text(extent = {{-150, 150}, {150, 110}}, textString = "%name", textColor = {0, 0, 255})}));\n`;

/** What a model or block can start from; "empty" is the plain class. */
export const TEMPLATES: Template[] = [
  { id: "empty", kind: "", label: "Empty", comment: "", detail: "Nothing inside: write its variables and equations, or draw it.", inner: "" },
  {
    id: "system", kind: "model", label: "System (an empty diagram to simulate)", comment: "A system of connected components",
    detail: "An empty diagram with simulation settings: drag components from the library or the project, connect them and simulate them together.",
    inner: `  annotation(experiment(StartTime = 0, StopTime = 10, Interval = 0.01, Tolerance = 1e-06),\n    Diagram(coordinateSystem(extent = {{-100, -100}, {100, 100}})));\n`,
  },
  {
    id: "signal-block", kind: "block", label: "Signal block (input to output)", comment: "A first-order signal block",
    detail: "A first-order block with an input u and an output y; change its equation. Connects to Modelica.Blocks.",
    inner: `  parameter Real k = 1 "Gain";\n  parameter Real T(min = 1e-9) = 1 "Time constant (s)";\n  Modelica.Blocks.Interfaces.RealInput u "Input" annotation(Placement(transformation(extent = {{-140, -20}, {-100, 20}})));\n  Modelica.Blocks.Interfaces.RealOutput y(start = 0) "Output" annotation(Placement(transformation(extent = {{100, -10}, {120, 10}})));\nequation\n  T * der(y) = k * u - y;\n${ICON("0, 0, 127", "k/(Ts+1)")}`,
  },
  {
    id: "thermal", kind: "model", label: "Thermal component (heat port)", comment: "A body that stores heat",
    detail: "A body that stores heat, with one heat port. Connects to Modelica.Thermal.HeatTransfer.",
    inner: `  parameter Modelica.Units.SI.HeatCapacity C = 1000 "Heat capacity";\n  Modelica.Units.SI.Temperature T(start = 293.15, fixed = true) "Temperature";\n  Modelica.Thermal.HeatTransfer.Interfaces.HeatPort_a port "Heat port" annotation(Placement(transformation(extent = {{-110, -10}, {-90, 10}})));\nequation\n  T = port.T;\n  C * der(T) = port.Q_flow;\n${ICON("191, 0, 0", "C")}`,
  },
  {
    id: "electrical", kind: "model", label: "Electrical component (two pins)", comment: "An electrical component between two pins",
    detail: "A component between two pins, a resistor to start from. Connects to Modelica.Electrical.Analog.",
    inner: `  extends Modelica.Electrical.Analog.Interfaces.OnePort;\n  parameter Modelica.Units.SI.Resistance R = 1 "Resistance";\nequation\n  v = R * i;\n${ICON("0, 0, 255", "R")}`,
  },
];

/** The templates a specialization can start from. */
export function templatesFor(restriction: string): Template[] {
  return TEMPLATES.filter((item) => !item.kind || item.kind === restriction);
}

export const CLASS_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;
const CLASS_PATH = /^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$/;

export interface ClassSpec {
  name: string;
  restriction: string;
  comment?: string;
  extends?: string;
  partial?: boolean;
  /** The package it goes in (`within`), "" at the top of the project. */
  within?: string;
  template?: string;
}

const quoted = (text: string) => text.replace(/\\/g, "\\\\").replace(/"/g, '\\"');

/** The text of a new class; null when the name, base class or package is not a Modelica name. */
export function classText(spec: ClassSpec): string | null {
  const name = spec.name.trim();
  const base = (spec.extends ?? "").trim();
  const within = (spec.within ?? "").trim();
  const template = TEMPLATES.find((item) => item.id === (spec.template || "empty"));
  if (!CLASS_NAME.test(name) || (base && !CLASS_PATH.test(base)) || (within && !CLASS_PATH.test(within))) return null;
  if (!template || !RESTRICTIONS.includes(spec.restriction) || (template.kind && template.kind !== spec.restriction)) return null;
  const comment = (spec.comment ?? "").trim() || template.comment;
  const description = comment ? ` "${quoted(comment)}"` : "";
  const head = within ? `within ${within};\n` : "";
  const partial = spec.partial ? "partial " : "";
  if (spec.restriction === "type") return `${head}${partial}type ${name} = ${base || "Real"}${description};\n`;
  const extend = base ? `  extends ${base};\n` : "";
  return `${head}${partial}${spec.restriction} ${name}${description}\n${extend}${template.inner}end ${name};\n`;
}

/** Where a new class's file goes: beside the package's `package.mo`, else at the top. */
export function classPath(name: string, packageFile: string | undefined): string {
  const folder = packageFile?.endsWith("/package.mo") ? packageFile.slice(0, -"package.mo".length) : "";
  return `${folder}${name}.mo`;
}

/** A package's `package.order` with the new class at its end (unchanged when it is listed). */
export function withOrder(order: string, name: string): string {
  const lines = order.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  return lines.includes(name) ? order : `${[...lines, name].join("\n")}\n`;
}

/** Whether a project class can be dropped into another class's diagram as a component. */
export function placeable(item: { restriction: string; partial: boolean; name: string }, into: string): boolean {
  return ["model", "block", "class"].includes(item.restriction) && !item.partial && item.name !== into;
}

/** The templates' labels in the interface language. */
export const templateLabel = (item: Template) => t(item.label);
