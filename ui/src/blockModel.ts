/**
 * The block diagram behind BlockEditor, as plain data: the catalog an app serves (each block's
 * ports, parameters and descriptions, `plantcraft_sdk.blocks.describe_block`), the diagram
 * (version 2: nodes and wires between named ports) and the edits people make to it. No React
 * here: every rule the editor applies (which ports may be wired, where a pasted block goes,
 * how "Arrange" lays blocks out) is a function of data, tested on its own.
 */
import { t } from "./i18n.js";

/** What a wire carries (`real`: a continuous value in time, Models' signals). */
export type PortType = "series" | "state" | "number" | "result" | "intervals" | "real";

export type PortSpec = {
  port: string;
  /** What an input accepts (an output has one type). */
  types: string[];
  type: string;
  label: string;
  description: string;
  unit: string;
  required: boolean;
  multiple: boolean;
  /** An output written to the historian unless the diagram says otherwise. */
  record: boolean;
};

export type ParameterSpec = {
  name: string;
  title: string;
  description: string;
  unit: string;
  default: unknown;
  /** The parameter's JSON schema (type, enum, minimum, maximum, items…). */
  schema: Record<string, unknown>;
};

export type BlockSpec = {
  block_id: string;
  library: string;
  group?: string;
  name: string;
  summary: string;
  description: string;
  reading: string;
  assumptions: string[];
  limitations: string[];
  formula?: string | null;
  references: string[];
  inputs: PortSpec[];
  outputs: PortSpec[];
  parameters: ParameterSpec[];
  runs_on_missing?: boolean;
  /** Its picture (round 9 M2): the URL the browser loads (`withImageHrefs`), none without one. */
  image?: string | null;
};

export type Library = { library: string; name: string; description: string; count?: number };
export type BlockCatalog = { libraries: Library[]; blocks: BlockSpec[] };

export type DiagramNode = {
  id: string;
  block: string;
  parameters?: Record<string, unknown>;
  /** Output ports written to the historian. */
  record?: string[];
  label?: string;
  x?: number;
  y?: number;
};

export type DiagramEdge = { source: string; source_port: string; target: string; target_port: string };
export type Diagram = { version?: number; nodes: DiagramNode[]; edges: DiagramEdge[] };

/** The app's check of a diagram (`Plan.report()`). */
export type DiagramCheck = {
  valid: boolean;
  errors: string[];
  warnings: string[];
  node_errors: Record<string, string[]>;
  node_warnings?: Record<string, string[]>;
  order?: string[];
};

/** What one output carried in a test run. */
export type TraceValue =
  | { type: "missing"; reason: string }
  | { type: "result"; status: string; value: number | null; message: string; label?: string }
  | { type: "series" | "state"; count: number; t: string[]; v: (number | string)[]; last: number | string | null }
  | { type: "number"; value: number }
  | { type: "none" };
export type DiagramTrace = Record<string, Record<string, TraceValue>>;

export const DIAGRAM_VERSION = 2;
export const COLUMN = 300;
export const ROW = 150;
/** A drawn block's size, near enough to frame a diagram (the node is 190-250 px wide). */
const NODE_W = 250;
const NODE_H = 120;

/**
 * The height that shows `diagram` across `width` (fit to the width, not to a fixed box: a
 * long algorithm in a short frame was drawn too small to read), between `min` and `max`.
 */
export function fitHeight(diagram: Diagram, width: number, min = 260, max = 900): number {
  if (!diagram.nodes.length || width <= 0) return min;
  const xs = diagram.nodes.map((node) => node.x ?? 0), ys = diagram.nodes.map((node) => node.y ?? 0);
  const w = Math.max(...xs) - Math.min(...xs) + NODE_W, h = Math.max(...ys) - Math.min(...ys) + NODE_H;
  const zoom = Math.min(1, width / (w * 1.3));
  return Math.round(Math.min(max, Math.max(min, h * 1.3 * zoom)));
}
// Conversions made on the wire (the engine's COERCIONS): a verdict feeds a number with its score.
const COERCIONS = new Set(["result>number"]);

export function emptyDiagram(): Diagram {
  return { version: DIAGRAM_VERSION, nodes: [], edges: [] };
}

export function byId(catalog: BlockCatalog): Record<string, BlockSpec> {
  return Object.fromEntries(catalog.blocks.map((block) => [block.block_id, block]));
}

/** Whether an input of `types` takes a wire carrying `source`. */
export function accepts(types: string[], source: string): boolean {
  return types.includes(source) || types.some((item) => COERCIONS.has(`${source}>${item}`));
}

export function nodeLabel(node: DiagramNode, blocks: Record<string, BlockSpec>): string {
  return node.label?.trim() || blocks[node.block]?.name || node.block;
}

/** The output port a wire leaves from, and the input it enters. */
export function edgePorts(edge: DiagramEdge, nodes: Record<string, DiagramNode>, blocks: Record<string, BlockSpec>) {
  const source = blocks[nodes[edge.source]?.block ?? ""]?.outputs.find((port) => port.port === edge.source_port);
  const target = blocks[nodes[edge.target]?.block ?? ""]?.inputs.find((port) => port.port === edge.target_port);
  return { source, target };
}

function reaches(edges: DiagramEdge[], from: string, to: string): boolean {
  const seen = new Set<string>();
  const stack = [from];
  while (stack.length) {
    const current = stack.pop() as string;
    if (current === to) return true;
    if (seen.has(current)) continue;
    seen.add(current);
    for (const edge of edges) if (edge.source === current) stack.push(edge.target);
  }
  return false;
}

/** How an app's diagrams may be wired. `loops`: a wire may close a loop (feedback, as in a
 * simulation model integrated over time); an algorithm run once from its inputs has none. */
export type WireRules = { loops?: boolean };

/**
 * Why a wire cannot be drawn, in words; empty when it can. A wire into an input that already
 * has one (and takes only one) replaces it, so that is allowed.
 */
export function wireProblem(diagram: Diagram, blocks: Record<string, BlockSpec>, wire: DiagramEdge, rules: WireRules = {}): string {
  const nodes = Object.fromEntries(diagram.nodes.map((node) => [node.id, node]));
  if (wire.source === wire.target) return t("A block cannot feed itself.");
  const { source, target } = edgePorts(wire, nodes, blocks);
  if (!source || !target) return t("Unknown port.");
  if (!accepts(target.types, source.type)) return t("{source} gives {type}; {target} takes {types}.", { source: source.label, type: source.type, target: target.label, types: target.types.join(t(" or ")) });
  if (diagram.edges.some((edge) => edge.source === wire.source && edge.source_port === wire.source_port && edge.target === wire.target && edge.target_port === wire.target_port)) {
    return t("Already wired.");
  }
  if (!rules.loops && reaches(diagram.edges, wire.target, wire.source)) return t("This wire would close a loop.");
  return "";
}

/** Add a wire; one into a single input replaces what was there. */
export function connect(diagram: Diagram, blocks: Record<string, BlockSpec>, wire: DiagramEdge, rules: WireRules = {}): Diagram {
  if (wireProblem(diagram, blocks, wire, rules)) return diagram;
  const nodes = Object.fromEntries(diagram.nodes.map((node) => [node.id, node]));
  const { target } = edgePorts(wire, nodes, blocks);
  const kept = target?.multiple
    ? diagram.edges
    : diagram.edges.filter((edge) => !(edge.target === wire.target && edge.target_port === wire.target_port));
  return { ...diagram, edges: [...kept, wire] };
}

/** The input ports (`node:port`) a wire from this output could enter, or the outputs for an input. */
export function compatiblePorts(
  diagram: Diagram,
  blocks: Record<string, BlockSpec>,
  from: { node: string; port: string; side: "source" | "target" },
  rules: WireRules = {},
): Set<string> {
  const found = new Set<string>();
  for (const node of diagram.nodes) {
    const spec = blocks[node.block];
    if (!spec || node.id === from.node) continue;
    const ports = from.side === "source" ? spec.inputs : spec.outputs;
    for (const port of ports) {
      const wire =
        from.side === "source"
          ? { source: from.node, source_port: from.port, target: node.id, target_port: port.port }
          : { source: node.id, source_port: port.port, target: from.node, target_port: from.port };
      if (!wireProblem(diagram, blocks, wire, rules)) found.add(`${node.id}:${port.port}`);
    }
  }
  return found;
}

/** A block name in snake case: `ControlValve` and `control_valve` give `control_valve`, `PID` gives `pid`. */
export function snakeCase(name: string): string {
  return name
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1_$2")
    .toLowerCase();
}

/** A node id from the block's name, unique in the diagram (`stiction_screening_2`, `control_valve`). */
export function newNodeId(block: string, taken: Iterable<string>): string {
  const used = new Set(taken);
  const base = snakeCase(block.split(".").pop() || "block").replace(/[^a-z0-9_]/g, "_").replace(/^[^a-z]+/, "") || "block";
  if (!used.has(base)) return base;
  let index = 2;
  while (used.has(`${base}_${index}`)) index += 1;
  return `${base}_${index}`;
}

/** The block's parameters at their defaults (what a new node starts with: nothing, so the
 * block's own defaults, and the site's, apply). */
export function addNode(diagram: Diagram, blocks: Record<string, BlockSpec>, block: string, at: { x: number; y: number }): { diagram: Diagram; id: string } {
  const spec = blocks[block];
  const id = newNodeId(block, diagram.nodes.map((node) => node.id));
  const node: DiagramNode = { id, block, parameters: {}, x: Math.round(at.x), y: Math.round(at.y) };
  const recorded = spec?.outputs.filter((port) => port.record).map((port) => port.port) ?? [];
  if (recorded.length) node.record = recorded;
  return { diagram: { ...diagram, nodes: [...diagram.nodes, node] }, id };
}

export function removeNodes(diagram: Diagram, ids: Iterable<string>): Diagram {
  const gone = new Set(ids);
  return {
    ...diagram,
    nodes: diagram.nodes.filter((node) => !gone.has(node.id)),
    edges: diagram.edges.filter((edge) => !gone.has(edge.source) && !gone.has(edge.target)),
  };
}

export function removeEdges(diagram: Diagram, keys: Iterable<string>): Diagram {
  const gone = new Set(keys);
  return { ...diagram, edges: diagram.edges.filter((edge) => !gone.has(edgeKey(edge))) };
}

export function edgeKey(edge: DiagramEdge): string {
  return `${edge.source}:${edge.source_port}>${edge.target}:${edge.target_port}`;
}

export function updateNode(diagram: Diagram, id: string, change: (node: DiagramNode) => DiagramNode): Diagram {
  return { ...diagram, nodes: diagram.nodes.map((node) => (node.id === id ? change(node) : node)) };
}

/** Set one parameter; `undefined` gives it back to its default. */
export function setParameter(diagram: Diagram, id: string, name: string, value: unknown): Diagram {
  return updateNode(diagram, id, (node) => {
    const parameters = { ...(node.parameters ?? {}) };
    if (value === undefined) delete parameters[name];
    else parameters[name] = value;
    return { ...node, parameters };
  });
}

export function toggleRecord(diagram: Diagram, id: string, port: string): Diagram {
  return updateNode(diagram, id, (node) => {
    const record = new Set(node.record ?? []);
    if (record.has(port)) record.delete(port);
    else record.add(port);
    const next: DiagramNode = { ...node, record: [...record] };
    if (!record.size) delete next.record;
    return next;
  });
}

export function moveNodes(diagram: Diagram, positions: Record<string, { x: number; y: number }>): Diagram {
  return {
    ...diagram,
    nodes: diagram.nodes.map((node) =>
      positions[node.id] ? { ...node, x: Math.round(positions[node.id].x), y: Math.round(positions[node.id].y) } : node,
    ),
  };
}

/** Copied blocks with the wires between them, ready to paste. */
export type Clip = { nodes: DiagramNode[]; edges: DiagramEdge[] };

export function copy(diagram: Diagram, ids: Iterable<string>): Clip {
  const chosen = new Set(ids);
  return {
    nodes: diagram.nodes.filter((node) => chosen.has(node.id)).map((node) => structuredClone(node)),
    edges: diagram.edges.filter((edge) => chosen.has(edge.source) && chosen.has(edge.target)).map((edge) => ({ ...edge })),
  };
}

/** Paste a clip with new ids, offset so the copy sits beside the original. */
export function paste(diagram: Diagram, clip: Clip, offset = 40): { diagram: Diagram; ids: string[] } {
  const taken = diagram.nodes.map((node) => node.id);
  const renamed: Record<string, string> = {};
  const nodes = clip.nodes.map((node) => {
    const id = newNodeId(node.id.replace(/_\d+$/, ""), [...taken, ...Object.values(renamed)]);
    renamed[node.id] = id;
    return { ...structuredClone(node), id, x: (node.x ?? 0) + offset, y: (node.y ?? 0) + offset };
  });
  const edges = clip.edges.map((edge) => ({ ...edge, source: renamed[edge.source], target: renamed[edge.target] }));
  return { diagram: { ...diagram, nodes: [...diagram.nodes, ...nodes], edges: [...diagram.edges, ...edges] }, ids: nodes.map((node) => node.id) };
}

/** What "Arrange" may know of the drawn diagram: each block's spec (where its ports sit) and its
 * drawn size (React Flow measures it); without them blocks are taken as NODE_W x NODE_H. */
export type ArrangeOptions = { blocks?: Record<string, BlockSpec>; sizes?: Record<string, { width: number; height: number }> };

/** Blank space between two columns and between two blocks of a column. */
const COLUMN_GAP = 110;
const ROW_GAP = 36;
/** Where a block's port rows start, under its header (and its picture), and how tall one is. */
const PORTS_TOP = 38;
const IMAGE_H = 70;
const PORT_ROW = 20;

/**
 * "Arrange": columns from inputs to outputs, each block one column after the last block that
 * feeds it; inside a column the blocks follow the order of what feeds them and what they feed
 * (a few barycentre sweeps, the usual way to cross fewer wires), and each block is moved level
 * with the ports its wires come from, as far as the blocks above it allow: no two blocks overlap,
 * whatever their height. Wires that close a loop (allowed in Models) are left out of the columns.
 */
export function arrange(diagram: Diagram, options: ArrangeOptions = {}): Diagram {
  const { blocks = {}, sizes = {} } = options;
  const ids = diagram.nodes.map((node) => node.id);
  const known = new Set(ids);
  const byNode = Object.fromEntries(diagram.nodes.map((node) => [node.id, node]));
  const wires = diagram.edges.filter((edge) => known.has(edge.source) && known.has(edge.target) && edge.source !== edge.target);
  // Wires back into a block still being walked close a loop: found walking from the blocks no
  // wire enters, then from the rest.
  const outgoing: Record<string, DiagramEdge[]> = Object.fromEntries(ids.map((id) => [id, []]));
  for (const edge of wires) outgoing[edge.source].push(edge);
  const fed = new Set(wires.map((edge) => edge.target));
  const back = new Set<DiagramEdge>();
  const state: Record<string, 1 | 2> = {};
  const walk = (id: string) => {
    state[id] = 1;
    for (const edge of outgoing[id]) {
      if (state[edge.target] === 1) back.add(edge);
      else if (!state[edge.target]) walk(edge.target);
    }
    state[id] = 2;
  };
  for (const id of [...ids.filter((id) => !fed.has(id)), ...ids]) if (!state[id]) walk(id);
  const forward = wires.filter((edge) => !back.has(edge));
  const incoming: Record<string, DiagramEdge[]> = Object.fromEntries(ids.map((id) => [id, []]));
  for (const edge of forward) incoming[edge.target].push(edge);
  const leaving: Record<string, DiagramEdge[]> = Object.fromEntries(ids.map((id) => [id, []]));
  for (const edge of forward) leaving[edge.source].push(edge);
  const rank: Record<string, number> = {};
  const rankOf = (id: string): number => {
    if (rank[id] === undefined) rank[id] = incoming[id].length ? Math.max(...incoming[id].map((edge) => rankOf(edge.source))) + 1 : 0;
    return rank[id];
  };
  ids.forEach(rankOf);
  // A block with nothing feeding it sits one column before the first block it feeds (an input
  // read only by the last block is not left far to the left).
  for (const id of ids) {
    if (incoming[id].length || !leaving[id].length) continue;
    rank[id] = Math.max(rank[id], Math.min(...leaving[id].map((edge) => rank[edge.target])) - 1);
  }
  const ranked: string[][] = [];
  for (const id of ids) (ranked[rank[id]] ??= []).push(id);
  // Columns an input left behind close up.
  const columns = ranked.filter((column) => column?.length);

  const spec = (id: string) => blocks[byNode[id]?.block ?? ""];
  const size = (id: string) => {
    const measured = sizes[id];
    if (measured && measured.width > 0 && measured.height > 0) return measured;
    const block = spec(id);
    if (!block) return { width: NODE_W, height: NODE_H };
    const rows = Math.max(block.inputs.length, block.outputs.length, 1);
    return { width: NODE_W, height: PORTS_TOP + (block.image ? IMAGE_H : 0) + rows * PORT_ROW + 10 };
  };
  const portTop = (id: string) => {
    const measured = sizes[id];
    const block = spec(id);
    const rows = block ? Math.max(block.inputs.length, block.outputs.length, 1) : 1;
    // A measured block: its port rows are its bottom ones.
    if (measured && measured.height > 0) return measured.height - 5 - rows * PORT_ROW;
    return PORTS_TOP + (block?.image ? IMAGE_H : 0);
  };
  const portIndex = (id: string, port: string, side: "in" | "out") => {
    const block = spec(id);
    const list = side === "in" ? block?.inputs : block?.outputs;
    const found = list?.findIndex((item) => item.port === port) ?? -1;
    return found < 0 ? 0 : found;
  };
  const portY = (id: string, port: string, side: "in" | "out") => portTop(id) + portIndex(id, port, side) * PORT_ROW + PORT_ROW / 2;

  // The order inside each column: sweeps down (by what feeds a block) and up (by what it feeds).
  const order: Record<string, number> = {};
  columns.forEach((column) => column.forEach((id, position) => (order[id] = position)));
  const centre = (edges: DiagramEdge[], other: (edge: DiagramEdge) => string, port: (edge: DiagramEdge) => [string, string, "in" | "out"]) => {
    if (!edges.length) return null;
    return edges.reduce((sum, edge) => sum + order[other(edge)] + portIndex(...port(edge)) / 100, 0) / edges.length;
  };
  const sortColumn = (column: string[], key: (id: string) => number | null) => {
    const keyed = column.map((id, position) => ({ id, key: key(id) ?? order[id] ?? position, position }));
    keyed.sort((a, b) => a.key - b.key || a.position - b.position);
    keyed.forEach((item, position) => (order[item.id] = position));
    return keyed.map((item) => item.id);
  };
  for (let sweep = 0; sweep < 4; sweep += 1) {
    for (let index = 1; index < columns.length; index += 1) {
      columns[index] = sortColumn(columns[index], (id) => centre(incoming[id], (edge) => edge.source, (edge) => [edge.source, edge.source_port, "out"]));
    }
    for (let index = columns.length - 2; index >= 0; index -= 1) {
      columns[index] = sortColumn(columns[index], (id) => centre(leaving[id], (edge) => edge.target, (edge) => [edge.target, edge.target_port, "in"]));
    }
  }

  // Where: x by column (as wide as its widest block), y level with the wires' other ends.
  const positions: Record<string, { x: number; y: number }> = {};
  let x = 40;
  const xs: number[] = [];
  for (const column of columns) {
    xs.push(x);
    const width = Math.max(0, ...column.map((id) => size(id).width));
    x += Math.max(COLUMN, width + COLUMN_GAP);
  }
  const place = (column: string[], index: number, wanted: (id: string) => number | null) => {
    let bottom = -Infinity;
    for (const id of column) {
      const want = wanted(id);
      const y = Math.max(want ?? (Number.isFinite(bottom) ? bottom : 40), Number.isFinite(bottom) ? bottom : -Infinity);
      positions[id] = { x: xs[index], y: Math.round(y) };
      bottom = y + size(id).height + ROW_GAP;
    }
  };
  const fromSources = (id: string) => {
    const edges = incoming[id].filter((edge) => positions[edge.source]);
    if (!edges.length) return null;
    return edges.reduce((sum, edge) => sum + positions[edge.source].y + portY(edge.source, edge.source_port, "out") - portY(id, edge.target_port, "in"), 0) / edges.length;
  };
  const fromTargets = (id: string) => {
    const edges = leaving[id].filter((edge) => positions[edge.target]);
    if (!edges.length) return null;
    return edges.reduce((sum, edge) => sum + positions[edge.target].y + portY(edge.target, edge.target_port, "in") - portY(id, edge.source_port, "out"), 0) / edges.length;
  };
  columns.forEach((column, index) => place(column, index, (id) => (index === 0 ? null : fromSources(id))));
  // Then the blocks nothing feeds move level with what they feed (the inputs on the left).
  columns.forEach((column, index) => {
    if (column.some((id) => incoming[id].length)) return;
    place(column, index, fromTargets);
  });
  // Nothing above the top margin.
  const top = Math.min(...Object.values(positions).map((item) => item.y));
  if (Number.isFinite(top) && top !== 40) for (const item of Object.values(positions)) item.y += 40 - top;
  return moveNodes(diagram, positions);
}

/** Undo and redo over whole diagrams (they are small). */
export type History = { past: Diagram[]; present: Diagram; future: Diagram[] };
export const HISTORY_LIMIT = 100;

export function startHistory(diagram: Diagram): History {
  return { past: [], present: diagram, future: [] };
}

export function record(history: History, next: Diagram): History {
  if (next === history.present) return history;
  return { past: [...history.past, history.present].slice(-HISTORY_LIMIT), present: next, future: [] };
}

export function undo(history: History): History {
  if (!history.past.length) return history;
  return { past: history.past.slice(0, -1), present: history.past[history.past.length - 1], future: [history.present, ...history.future] };
}

export function redo(history: History): History {
  if (!history.future.length) return history;
  return { past: [...history.past, history.present], present: history.future[0], future: history.future.slice(1) };
}

/** What a wire carried in a test run, in a few characters for its label. */
export function traceText(value: TraceValue | undefined, locale = "en-US"): string {
  if (!value) return "";
  const number = (item: number) => item.toLocaleString(locale, { maximumSignificantDigits: 4 });
  switch (value.type) {
    case "missing":
      return "—";
    case "result":
      return value.value === null ? value.status : `${value.status} ${number(value.value)}`;
    case "number":
      return number(value.value);
    case "series":
      return value.last === null ? `0 pts` : `${value.count} pts · ${typeof value.last === "number" ? number(value.last) : value.last}`;
    case "state":
      return `${value.count} pts · ${value.last ?? ""}`;
    default:
      return "";
  }
}

/** Libraries in the catalog's order, each with its blocks, filtered by a search. */
export function palette(catalog: BlockCatalog, search: string): { library: Library; blocks: BlockSpec[] }[] {
  const words = search.toLowerCase().split(/\s+/).filter(Boolean);
  const match = (block: BlockSpec) => {
    const text = `${block.name} ${block.summary} ${block.block_id} ${block.group ?? ""}`.toLowerCase();
    return words.every((word) => text.includes(word));
  };
  return catalog.libraries
    .map((library) => ({ library, blocks: catalog.blocks.filter((block) => block.library === library.library && match(block)) }))
    .filter((item) => item.blocks.length);
}

/** The value a parameter shows: the diagram's, else the block's default. */
export function parameterValue(node: DiagramNode, parameter: ParameterSpec): unknown {
  const own = node.parameters?.[parameter.name];
  return own === undefined ? parameter.default : own;
}

/** A block's light in a test run: the first verdict among its outputs, else grey when none came. */
export function blockLight(block: BlockSpec, values: Record<string, TraceValue> | undefined): { status: string; text: string } | null {
  if (!values) return null;
  for (const port of block.outputs) {
    const value = values[port.port];
    if (value?.type === "result") return { status: value.status, text: value.message || value.status };
  }
  const missing = block.outputs.map((port) => values[port.port]).find((value) => value?.type === "missing");
  return missing?.type === "missing" ? { status: "unknown", text: missing.reason } : null;
}

/** What reached one input in a test run: the value on each wire into it. */
export function inputTraces(diagram: Diagram, trace: DiagramTrace | null | undefined, nodeId: string, port: string): { source: DiagramEdge; value: TraceValue }[] {
  if (!trace) return [];
  return diagram.edges
    .filter((edge) => edge.target === nodeId && edge.target_port === port)
    .flatMap((edge) => {
      const value = trace[edge.source]?.[edge.source_port];
      return value ? [{ source: edge, value }] : [];
    });
}

/** A series drawn in a `width` × `height` box: the SVG path and the range it spans. */
export function seriesPath(values: (number | string)[], width: number, height: number): { d: string; min: number; max: number } | null {
  const numbers = values.map(Number).filter((item) => Number.isFinite(item));
  if (!numbers.length) return null;
  const min = Math.min(...numbers);
  const max = Math.max(...numbers);
  const span = max - min || 1;
  const step = values.length > 1 ? width / (values.length - 1) : 0;
  let d = "";
  let pen = false;
  values.forEach((raw, index) => {
    const value = Number(raw);
    if (!Number.isFinite(value)) {
      pen = false;
      return;
    }
    const x = values.length > 1 ? index * step : width / 2;
    const y = max === min ? height / 2 : height - ((value - min) / span) * height;
    d += `${pen ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
    pen = true;
  });
  return { d, min, max };
}

/** A text signal (a mode) as runs of the same value, each a share of the window. */
export function stateRuns(values: (number | string)[]): { value: string; start: number; share: number }[] {
  const runs: { value: string; start: number; share: number }[] = [];
  values.forEach((raw, index) => {
    const value = String(raw);
    const last = runs[runs.length - 1];
    if (last && last.value === value) last.share += 1;
    else runs.push({ value, start: index, share: 1 });
  });
  return runs.map((run) => ({ ...run, start: run.start / values.length, share: run.share / values.length }));
}
