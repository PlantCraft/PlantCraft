/**
 * A diagram written as text (2026-10-26): what the assistant's "new algorithm" card carries, so
 * the diagram's window opens with the blocks placed and wired instead of empty. One line each:
 *
 *   pv = input.signal            a block, by its id (or its name)
 *   pv -> frozen                 a wire; the first output that fits the first free input
 *   frozen.verdict -> out.state  a wire between named ports
 *   frozen.hours = 3             a parameter (JSON, or the text as it is)
 *   frozen = dq.frozen(series = pv, hours = 3)   the same as a call (2026-10-26: models write it)
 *
 * A port name the block does not have is read as "any port that fits".
 * What cannot be read is said in `problems`; the rest is kept and arranged left to right.
 */
import { addNode, arrange, emptyDiagram, wireProblem, type BlockCatalog, type BlockSpec, type Diagram, type DiagramEdge } from "@plantcraft/ui/blockEditor";

export type Sketch = { diagram: Diagram; problems: string[] };

const WIRE = /^([\w-]+)(?:\.([\w-]+))?\s*(?:->|→)\s*([\w-]+)(?:\.([\w-]+))?$/;
const PARAMETER = /^([\w-]+)\.([\w-]+)\s*[=:]\s*(.+)$/;
const NODE = /^([\w-]+)\s*[=:]\s*(.+)$/;
const CALL = /^([^()]+)\((.*)\)$/;
const SOURCE = /^([\w-]+)(?:\.([\w-]+))?$/;

function findBlock(blocks: BlockSpec[], text: string): BlockSpec | undefined {
  const wanted = text.trim().replace(/^`|`$/g, "").toLowerCase();
  return blocks.find((block) => block.block_id.toLowerCase() === wanted)
    ?? blocks.find((block) => block.name.toLowerCase() === wanted)
    ?? blocks.find((block) => block.block_id.toLowerCase().split(".").pop() === wanted);
}

/** The ports of that name; a name the block does not have leaves every port to choose from. */
function byName<T extends { port: string }>(ports: T[], name?: string): T[] {
  return name && ports.some((port) => port.port === name) ? ports.filter((port) => port.port === name) : ports;
}

function value(text: string): unknown {
  try { return JSON.parse(text); } catch { return text.trim(); }
}

export function sketchDiagram(text: string, catalog: Pick<BlockCatalog, "blocks">): Sketch {
  const specs = Object.fromEntries(catalog.blocks.map((block) => [block.block_id, block]));
  const problems: string[] = [];
  let diagram = emptyDiagram();
  const named: Record<string, string> = {};
  const wires: Array<{ line: string; source: string; sourcePort?: string; target: string; targetPort?: string }> = [];
  const parameters: Array<{ line: string; node: string; name: string; value: unknown }> = [];
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.replace(/^\s*[-*\d.)]+\s+/, "").trim();
    if (!line || line.startsWith("#")) continue;
    const wire = WIRE.exec(line);
    const parameter = !wire && PARAMETER.exec(line);
    const node = !wire && !parameter && NODE.exec(line);
    if (wire) wires.push({ line, source: wire[1], sourcePort: wire[2], target: wire[3], targetPort: wire[4] });
    else if (parameter) parameters.push({ line, node: parameter[1], name: parameter[2], value: value(parameter[3]) });
    else if (node) {
      const call = CALL.exec(node[2].trim());
      const block = findBlock(catalog.blocks, call ? call[1] : node[2]);
      if (!block && /^[-+\d."']/.test(node[2].trim())) { problems.push(`${line}: a constant is a block's parameter, not a block.`); continue; }
      if (!block) { problems.push(`Unknown block: ${(call ? call[1] : node[2]).trim()}`); continue; }
      if (named[node[1]]) { problems.push(`${node[1]} is named twice.`); continue; }
      const added = addNode(diagram, specs, block.block_id, { x: 0, y: 0 });
      // The node keeps the name the text gave it when it is free.
      const id = /^[a-z][a-z0-9_]*$/.test(node[1]) && !diagram.nodes.some((item) => item.id === node[1]) ? node[1] : added.id;
      diagram = { ...added.diagram, nodes: added.diagram.nodes.map((item) => (item.id === added.id ? { ...item, id } : item)) };
      named[node[1]] = id;
      // A call's arguments: `port = source[.port]` and bare `source` are wires, the rest parameters.
      for (const argument of call ? call[2].split(",").map((item) => item.trim()).filter(Boolean) : []) {
        const [key, given] = argument.includes("=") ? argument.split("=").map((item) => item.trim()) : ["", argument];
        const from = SOURCE.exec(given);
        if (key && block.parameters.some((item) => item.name === key) && !(from && named[from[1]])) parameters.push({ line, node: node[1], name: key, value: value(given) });
        else if (from) wires.push({ line, source: from[1], sourcePort: from[2], target: node[1], targetPort: key || undefined });
        else problems.push(`Not understood: ${argument} in ${line}`);
      }
    } else problems.push(`Not understood: ${line}`);
  }
  const block = (id: string) => specs[diagram.nodes.find((node) => node.id === id)?.block ?? ""];
  // A wire may name a block by its id's part instead of its node (`det.value -> output.value`):
  // the one node of that block, when there is one.
  const node = (name: string) => {
    if (named[name]) return named[name];
    const found = diagram.nodes.filter((item) => item.block.split(".").includes(name));
    return found.length === 1 ? found[0].id : undefined;
  };
  for (const wire of wires) {
    const source = node(wire.source);
    const target = node(wire.target);
    if (!source || !target) { problems.push(`Unknown block in: ${wire.line}`); continue; }
    const outputs = byName(block(source).outputs, wire.sourcePort);
    const free = (port: string) => !diagram.edges.some((edge) => edge.target === target && edge.target_port === port);
    const inputs = byName(block(target).inputs, wire.targetPort);
    // An input taken by an earlier line keeps its wire, unless it takes several.
    const ordered = [...inputs.filter((port) => free(port.port)), ...inputs.filter((port) => !free(port.port) && port.multiple)];
    let chosen: DiagramEdge | null = null;
    let why = "No port fits.";
    for (const input of ordered) {
      for (const output of outputs) {
        const candidate = { source, source_port: output.port, target, target_port: input.port };
        const problem = wireProblem(diagram, specs, candidate);
        if (!problem) { chosen = candidate; break; }
        why = problem;
      }
      if (chosen) break;
    }
    if (chosen) diagram = { ...diagram, edges: [...diagram.edges, chosen] };
    else problems.push(`${wire.line}: ${why}`);
  }
  for (const parameter of parameters) {
    const id = named[parameter.node];
    if (!id || !block(id).parameters.some((item) => item.name === parameter.name)) { problems.push(`Unknown parameter: ${parameter.line}`); continue; }
    diagram = { ...diagram, nodes: diagram.nodes.map((node) => (node.id === id ? { ...node, parameters: { ...node.parameters, [parameter.name]: parameter.value } } : node)) };
  }
  return { diagram: diagram.nodes.length ? arrange(diagram) : diagram, problems };
}
