/**
 * A rule's parts as the editor keeps them (Alarms round 11): the Simple form's conditions, where
 * it applies, and the Python form, which is a diagram of a few value blocks wired into one
 * Python block and the Raise an alarm block. The server writes the Simple form's diagram.
 */
import type { Diagram, DiagramNode } from "@plantcraft/ui/blockEditor";
import { t } from "./i18n";
import { NEW_NOTIFY } from "./notify";
import type { ExplorePick } from "@plantcraft/ui";
import type { Rule, RuleDraft, SimpleCondition, SimpleLogic, SimpleValue, Where } from "./types";

export const MAX_CONDITIONS = 3;
export const ASSET = "{asset}";
export const PYTHON_BLOCK = "alarm.python";
export const VALUE_BLOCK = "alarm.value";
export const RAISE_BLOCK = "alarm.raise";

export const NO_WHERE = (): Where => ({ assets: [], under: [], types: [], executions: [], anywhere: false, per: "asset" });

export const NO_VALUE = (): SimpleValue => ({ signal: "", role: "pv", name: "", unit: "" });

/** Whether every condition is filled in as the server wants it (``SimpleCondition._complete``):
 * until then there is no sentence to ask for, and asking would only answer 422. */
export function simpleComplete(simple: SimpleLogic): boolean {
  const complete = (item: SimpleCondition) => {
    if (item.input === "event") return item.event !== null;
    if (item.value === null || !(item.value.signal || item.value.role)) return false;
    if (item.op === "between" || item.op === "outside") return item.limit !== null && item.high !== null && item.high >= item.limit;
    return item.op === "changed" || item.op === "unchanged" || item.limit !== null;
  };
  return simple.conditions.every(complete) && (!simple.enable_when || complete(simple.enable_when));
}

/** A new permissive: a running signal at or above 1 (a pump's run feedback). */
export const NEW_PERMISSIVE = (): SimpleCondition => ({ ...valueCondition({ signal: "", role: "", name: "", unit: "" }), op: ">=", limit: 1 });

export function valueCondition(value: SimpleValue = NO_VALUE()): SimpleCondition {
  return {
    input: "value", value, op: ">", limit: null, high: null, deadband: 0,
    event: null, test: "open", count: 1, window_minutes: 60, for_seconds: 0, for_points: 0,
  };
}

export function eventCondition(kinds: string[] = [], about = "subject"): SimpleCondition {
  return {
    ...valueCondition(), input: "event", value: null,
    event: { kinds, severities: [], about, name: "" },
  };
}

export const EMPTY_SIMPLE = (): SimpleLogic => ({ conditions: [valueCondition()], combine: "and", clear_after_seconds: 0, enable_when: null, enable_delay_seconds: 0 });

export const EMPTY_RULE = (): RuleDraft => ({
  name: "", enabled: true, creates: "alarm", priority: "medium", where: NO_WHERE(),
  editor: "simple", simple: EMPTY_SIMPLE(), diagram: { version: 2, nodes: [], edges: [] },
  owner: null, area: null, discipline: null, notify: NEW_NOTIFY(), dashboards: true, cause: "", consequence: "", action: "",
});

/** The fields of a stored rule (or a prefilled one) a person edits. */
export function draftOf(rule: Partial<Rule> | Partial<RuleDraft>): RuleDraft {
  const empty = EMPTY_RULE();
  const draft = Object.fromEntries(Object.keys(empty).map((key) => [key, (rule as Record<string, unknown>)[key] ?? (empty as unknown as Record<string, unknown>)[key]])) as unknown as RuleDraft;
  const simple = draft.editor === "simple" ? fillSimple(draft.simple) : null;
  return { ...draft, simple, where: { ...NO_WHERE(), ...draft.where }, notify: { ...NEW_NOTIFY(), ...(rule.notify ?? {}) } };
}

function fillSimple(simple: SimpleLogic | null): SimpleLogic {
  if (!simple?.conditions?.length) return EMPTY_SIMPLE();
  return {
    ...EMPTY_SIMPLE(), ...simple,
    conditions: simple.conditions.map((item) => item.input === "event"
      ? { ...eventCondition(), ...item, event: { ...eventCondition().event!, ...(item.event ?? {}) } }
      : { ...valueCondition(), ...item, value: { ...NO_VALUE(), ...(item.value ?? {}) } }),
    enable_when: simple.enable_when ? { ...valueCondition(), ...simple.enable_when, value: { ...NO_VALUE(), ...(simple.enable_when.value ?? {}) } } : null,
    enable_delay_seconds: simple.enable_delay_seconds ?? 0,
  };
}

/** Whether the rule covers assets (so "this asset" means each of them). */
export function overAssets(where: Where): boolean {
  return where.anywhere || where.assets.length + where.under.length + where.types.length + where.executions.length > 0;
}

/** A picked value or event as the Simple form keeps it. ``each``: read on each asset of the rule
 * (the signal's role, or an app's series with the asset left open). */
export function valueOfPick(pick: ExplorePick, each: boolean): SimpleValue {
  const name = pick.path.length ? `${pick.path[pick.path.length - 1].name} › ${pick.name}` : pick.name;
  if (each && pick.type === "signal" && pick.role) return { signal: "", role: pick.role, name: pick.name, unit: pick.unit ?? "" };
  if (each && pick.type === "output" && pick.relativeTo) {
    const open = relativeSignal(pick.id, pick.relativeTo);
    if (open) return { signal: open, role: "", name: pick.name, unit: pick.unit ?? "" };
  }
  return { signal: pick.id, role: "", name, unit: pick.unit ?? "" };
}

/** ``app-linkcraft:FIC-1001.health.score`` on FIC-1001 → ``app-linkcraft:{asset}.health.score``. */
export function relativeSignal(signal: string, asset: string): string | null {
  const marker = `:${asset}.`;
  const at = signal.indexOf(marker);
  return at < 0 ? null : `${signal.slice(0, at)}:${ASSET}.${signal.slice(at + marker.length)}`;
}

/** Whether a pick can be read on each asset of a rule. */
export function canBeRelative(pick: ExplorePick): boolean {
  return (pick.type === "signal" && Boolean(pick.role)) || (pick.type === "output" && Boolean(pick.relativeTo && relativeSignal(pick.id, pick.relativeTo)));
}

export function valueWords(value: SimpleValue | null): string {
  if (!value) return "";
  if (value.name) return value.signal.includes(ASSET) || (!value.signal && value.role) ? `${value.name} (${eachAssetWord()})` : value.name;
  return value.signal ? value.signal.replace(ASSET, eachAssetWord()) : value.role;
}

const eachAssetWord = () => t("each asset");

// The Python form ---------------------------------------------------------------------------

export interface PythonInput { label: string; value: SimpleValue }
export interface PythonForm { inputs: PythonInput[]; code: string; clearAfter: number }

/** The example a Python rule starts from (owner's review, 2026-10-27: prefilled, saying what
 * comes in and what goes out): each input checked for no data, one limit, the answer with its
 * sentence. Written for the inputs the rule has (a placeholder name when it has none). */
export function pythonTemplate(labels: string[]): string {
  const names = labels.length ? labels : ["value"];
  const first = names[0];
  return [
    "def check(inputs):",
    "    \"\"\"Decide whether the alarm is raised, once a minute, for each asset of the rule.",
    "",
    "    inputs: the last reading of each input, by its name:",
    ...names.map((name) => `        inputs.${name}`),
    "      a number (True/False for a yes/no value), or None when there is no data.",
    "    Answer (raise, sentence): True raises the alarm and shows the sentence with it;",
    "    False does not raise, or clears it.",
    "    \"\"\"",
    `    if ${names.map((name) => `inputs.${name} is None`).join(" or ")}:`,
    "        return False, \"\"  # no data: Historian's no-data events say so",
    "",
    "    limit = 100.0  # change to your limit",
    `    if inputs.${first} > limit:`,
    `        return True, f"${first} {inputs.${first}:.4g} above {limit:g}"`,
    "    return False, \"\"",
    "",
  ].join("\n");
}

export const PYTHON_TEMPLATE = pythonTemplate([]);

/** A Python-friendly name: "Flow PV" → "flow_pv". */
export function inputLabel(text: string, taken: string[]): string {
  let base = text.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 30) || "value";
  if (/^\d/.test(base)) base = `v_${base}`;
  let label = base;
  for (let number = 2; taken.includes(label); number += 1) label = `${base}_${number}`;
  return label;
}

export function pythonDiagram(form: PythonForm): Diagram {
  const nodes: DiagramNode[] = form.inputs.map((input, index) => ({
    id: `v${index + 1}`, block: VALUE_BLOCK, label: input.label, x: 0, y: index * 150,
    parameters: { signal: input.value.signal, role: input.value.role, unit: input.value.unit },
  }));
  const middle = Math.max(0, (form.inputs.length - 1) * 75);
  nodes.push({ id: "python", block: PYTHON_BLOCK, label: "Python", x: 300, y: middle, parameters: { code: form.code } });
  nodes.push({ id: "alarm", block: RAISE_BLOCK, label: "Raise", x: 600, y: middle, parameters: { clear_after_seconds: form.clearAfter } });
  const edges = form.inputs.map((_, index) => ({ source: `v${index + 1}`, source_port: "value", target: "python", target_port: "values" }));
  edges.push({ source: "python", source_port: "condition", target: "alarm", target_port: "condition" });
  return { version: 2, nodes, edges };
}

/** The Python form of a diagram (its value blocks wired into its Python block), or null when the
 * diagram holds more than that and only Blocks shows it whole. */
export function pythonForm(diagram: Diagram): PythonForm | null {
  const python = diagram.nodes.find((node) => node.block === PYTHON_BLOCK);
  const raise = diagram.nodes.find((node) => node.block === RAISE_BLOCK);
  if (!python || !raise || diagram.nodes.some((node) => ![VALUE_BLOCK, PYTHON_BLOCK, RAISE_BLOCK].includes(node.block))) return null;
  const byId = Object.fromEntries(diagram.nodes.map((node) => [node.id, node]));
  const inputs = diagram.edges.filter((edge) => edge.target === python.id).map((edge) => byId[edge.source]).filter((node) => node?.block === VALUE_BLOCK).map((node) => {
    const params = node.parameters ?? {};
    return { label: node.label || node.id, value: { signal: String(params.signal ?? ""), role: String(params.role ?? ""), name: node.label ?? "", unit: String(params.unit ?? "") } };
  });
  return { inputs, code: String(python.parameters?.code ?? PYTHON_TEMPLATE), clearAfter: Number(raise.parameters?.clear_after_seconds ?? 0) };
}

/** The values of a Simple form, as the first inputs of a Python form. */
export function pythonFromSimple(simple: SimpleLogic | null): PythonForm {
  const inputs: PythonInput[] = [];
  for (const condition of simple?.conditions ?? []) {
    if (condition.input !== "value" || !condition.value) continue;
    inputs.push({ label: inputLabel(condition.value.name || condition.value.role || condition.value.signal, inputs.map((item) => item.label)), value: condition.value });
  }
  return { inputs, code: pythonTemplate(inputs.map((item) => item.label)), clearAfter: simple?.clear_after_seconds ?? 0 };
}

/** A new rule for one Link schedule (its page's "Create alarm rule"): each asset it runs on,
 * critical in that schedule, one alarm per asset, cleared when the status is back. */
export function scheduleRule(scheduleId: string, name?: string, app = "linkcraft"): RuleDraft {
  const condition = eventCondition([`${app}.status.changed`]);
  condition.event!.severities = ["critical"];
  return {
    ...EMPTY_RULE(), priority: "medium",
    name: `${name || scheduleId}: asset critical`.slice(0, 120),
    where: { ...NO_WHERE(), executions: [`${app}:${scheduleId}`] },
    simple: { conditions: [condition], combine: "and", clear_after_seconds: 0 },
  };
}

/** "5 min", "90 s", "2 h" for a number of seconds. */
export function secondsWords(seconds: number): string {
  if (seconds >= 3600 && seconds % 3600 === 0) return `${seconds / 3600} h`;
  if (seconds >= 60 && seconds % 60 === 0) return `${seconds / 60} min`;
  return `${seconds} s`;
}
