/**
 * BlockEditor: the suite's block diagram editor, Simulink style, for any app that runs
 * algorithms made of blocks (PlantCraft Analytics today, Models next). The app hands it its block
 * catalog (`GET /api/blocks`: ports, parameters and descriptions) and a diagram, and gets every
 * edit back through `onChange`; checking, testing and saving stay the app's (its check report
 * and its test trace come back in as props and are drawn on the blocks and the wires).
 *
 * What people get, the same in every app:
 * - a palette of the catalog's libraries, searchable, dragged or clicked onto the canvas;
 * - ports coloured by what they carry; while a wire is drawn the inputs it can enter light up
 *   and the others fade; a wire that does not fit is refused with the reason;
 * - an inspector written from the block's own descriptions: its parameters (with units,
 *   defaults and limits), its inputs and outputs, the toggle that records an output in the
 *   historian, and what the block does, how to read it and its limits;
 * - the check's problems on the blocks they concern, and a test run's values on the wires;
 * - undo and redo, copy and paste, delete, "Arrange" and fit to screen, with the usual keys.
 *
 * Exported from `@plantcraft/ui/blockEditor` (it needs `@xyflow/react`, which apps without
 * diagrams do not install). Styles: `@plantcraft/ui/blockEditor.css`.
 */
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  applyNodeChanges,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
  type NodeChange,
  type NodeProps,
  type OnConnectStartParams,
} from "@xyflow/react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  ClipboardPaste,
  Copy,
  Database,
  Eye,
  EyeOff,
  Maximize,
  Plus,
  Redo2,
  RotateCcw,
  Search,
  Trash2,
  Undo2,
  Workflow,
} from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type DragEvent, type KeyboardEvent, type ReactNode } from "react";
import {
  addNode,
  arrange,
  blockLight,
  byId,
  compatiblePorts,
  connect,
  copy,
  edgeKey,
  inputTraces,
  moveNodes,
  nodeLabel,
  palette,
  parameterValue,
  paste,
  record,
  redo,
  removeEdges,
  removeNodes,
  seriesPath,
  setParameter,
  startHistory,
  stateRuns,
  toggleRecord,
  traceText,
  undo,
  updateNode,
  wireProblem,
  type BlockCatalog,
  type BlockSpec,
  type Clip,
  type Diagram,
  type DiagramCheck,
  type DiagramNode,
  type DiagramTrace,
  type History,
  type ParameterSpec,
  type PortSpec,
  type TraceValue,
} from "./blockModel.js";
import { t, uiLocale } from "./i18n.js";
import { displayTimeZone } from "./timeZone.js";
import { renderMarkdown } from "./Markdown.js";
import { ParameterField, typeLabel } from "./blockParameter.js";

export { ParameterField, typeLabel } from "./blockParameter.js";

export type BlockEditorProps = {
  catalog: BlockCatalog;
  diagram: Diagram;
  /** Every edit, as the whole new diagram. Without it the editor is read-only. */
  onChange?: (diagram: Diagram) => void;
  readOnly?: boolean;
  /** The app's check of the current diagram. */
  check?: DiagramCheck | null;
  /** What each output carried in the app's last test run. */
  trace?: DiagramTrace | null;
  /** Left of the toolbar (the algorithm's name). */
  title?: ReactNode;
  /** Right of the toolbar (Test, Save, Duplicate…). */
  actions?: ReactNode;
  /** The inspector when no block is selected (the algorithm's documentation, where it is used). */
  aside?: ReactNode;
  /** Link to a block's own page from the inspector. */
  blockHref?: (blockId: string) => string;
  /** The app's own tools for the selected block, shown in the inspector under its name (a
   * deviation block's Calibrate); nothing for blocks the app has no tool for. */
  inspectorTools?: (node: DiagramNode) => ReactNode;
  /** An extra class on the editor's frame. */
  className?: string;
  /** Wires may close loops (feedback): a simulation model integrated over time has them; an
   * algorithm run once from its inputs does not (the default). */
  allowLoops?: boolean;
};

type Connecting = { node: string; port: string; side: "source" | "target" } | null;

type EditorContextValue = {
  blocks: Record<string, BlockSpec>;
  diagram: Diagram;
  check?: DiagramCheck | null;
  trace?: DiagramTrace | null;
  compatible: Set<string> | null;
  libraryIndex: Record<string, number>;
};

const EditorContext = createContext<EditorContextValue | null>(null);
const useEditor = () => useContext(EditorContext) as EditorContextValue;

const RECORDABLE = new Set(["number", "result", "series"]);

// --- the block on the canvas -----------------------------------------------------------------

type BlockData = { node: DiagramNode };
type BlockFlowNode = Node<BlockData, "block">;

function PortHandle({ nodeId, port, side }: { nodeId: string; port: PortSpec; side: "source" | "target" }) {
  const { compatible } = useEditor();
  const key = `${nodeId}:${port.port}`;
  const state = compatible ? (compatible.has(key) ? " be-compatible" : " be-dim") : "";
  return (
    <Handle
      type={side}
      id={port.port}
      position={side === "source" ? Position.Right : Position.Left}
      className={`be-handle be-type-${port.type}${state}${side === "target" && !port.required ? " be-optional" : ""}`}
      title={`${port.label} · ${typeLabel(port.type)}${port.unit ? ` (${port.unit})` : ""}\n${port.description}`}
    />
  );
}

function BlockNodeView({ id, data, selected }: NodeProps<BlockFlowNode>) {
  const { blocks, check, trace, libraryIndex } = useEditor();
  const node = data.node;
  const spec = blocks[node.block];
  const issues = check?.node_errors?.[id] ?? [];
  const warnings = check?.node_warnings?.[id] ?? [];
  const recorded = new Set(node.record ?? []);
  if (!spec) {
    return (
      <div className="be-node be-unknown" data-selected={selected || undefined}>
        <header><AlertTriangle size={13} /><strong>{node.block}</strong></header>
        <p className="be-issue">{t("This block is not in the catalog.")}</p>
      </div>
    );
  }
  const rows = Math.max(spec.inputs.length, spec.outputs.length);
  const label = nodeLabel(node, blocks);
  // The block shows a light; what the run said, and the check's problems, show on hover.
  const light = blockLight(spec, trace?.[id]);
  const notes = [...issues, ...warnings];
  return (
    <div
      className={`be-node be-lib-${libraryIndex[spec.library] ?? 0}${issues.length ? " be-has-issue" : ""}`}
      data-selected={selected || undefined}
      data-block={spec.block_id}
    >
      <header>
        <span className="be-node-title">
          <strong title={spec.summary}>{label}</strong>
          {label !== spec.name && <small>{spec.name}</small>}
        </span>
        {issues.length > 0 && <AlertTriangle size={13} className="be-node-alert" aria-label={issues.join(" ")} />}
        {light && <i className={`be-light be-status-${light.status}`} data-status={light.status} role="img" aria-label={light.text} />}
      </header>
      {spec.image && <img className="be-node-image" src={spec.image} alt="" draggable={false} loading="lazy" />}
      <div className="be-ports">
        {Array.from({ length: rows }, (_, index) => {
          const input = spec.inputs[index];
          const output = spec.outputs[index];
          return (
            <div className="be-port-row" key={index}>
              <span className="be-port be-port-in">
                {input && <PortHandle nodeId={id} port={input} side="target" />}
                {input && <span>{input.label}{input.multiple ? " …" : ""}</span>}
              </span>
              <span className="be-port be-port-out">
                {output && recorded.has(output.port) && <Database size={10} className="be-recorded" aria-label={t("Recorded in the historian")} />}
                {output && <span>{output.label}</span>}
                {output && <PortHandle nodeId={id} port={output} side="source" />}
              </span>
            </div>
          );
        })}
      </div>
      {(light || notes.length > 0) && (
        <div className="be-tip" role="tooltip">
          {light && <p className={`be-tip-verdict be-status-${light.status}`}><i className={`be-light be-status-${light.status}`} />{light.text}</p>}
          {issues.map((item) => <p key={item} className="be-issue"><AlertTriangle size={11} /> {item}</p>)}
          {warnings.map((item) => <p key={item} className="be-warning">{item}</p>)}
        </div>
      )}
    </div>
  );
}

const NODE_TYPES = { block: BlockNodeView };

// --- the inspector ---------------------------------------------------------------------------

// --- what a test run carried, in the inspector --------------------------------------------

type SampledTrace = Extract<TraceValue, { count: number }>;

const CHART_W = 280;
const CHART_H = 64;

function shortTime(stamp: string | undefined): string {
  if (!stamp) return "";
  const date = new Date(stamp);
  return Number.isNaN(date.getTime()) ? stamp : date.toLocaleString(uiLocale(), { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: displayTimeZone() });
}

function number(value: number): string {
  return value.toLocaleString(uiLocale(), { maximumSignificantDigits: 4 });
}

function SeriesChart({ value, unit }: { value: SampledTrace; unit: string }) {
  const [at, setAt] = useState<number | null>(null);
  const drawn = seriesPath(value.v, CHART_W, CHART_H);
  if (!drawn) return <p className="be-trace-empty">{t("No numeric samples.")}</p>;
  const index = at === null ? null : Math.min(value.v.length - 1, Math.max(0, Math.round((at / CHART_W) * (value.v.length - 1))));
  const shown = index === null ? value.last : value.v[index];
  const x = index === null ? null : value.v.length > 1 ? (index / (value.v.length - 1)) * CHART_W : CHART_W / 2;
  return (
    <div className="be-chart">
      <div className="be-chart-head">
        <b>{typeof shown === "number" ? number(shown) : String(shown ?? "—")}{unit ? ` ${unit}` : ""}</b>
        <small>{index === null ? t("min {min} · max {max}", { min: number(drawn.min), max: number(drawn.max) }) : shortTime(value.t[index])}</small>
      </div>
      <svg
        viewBox={`0 0 ${CHART_W} ${CHART_H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={t("{count} values from {start} to {end}", { count: value.count, start: shortTime(value.t[0]), end: shortTime(value.t[value.t.length - 1]) })}
        onMouseMove={(event) => {
          const box = event.currentTarget.getBoundingClientRect();
          setAt(((event.clientX - box.left) / box.width) * CHART_W);
        }}
        onMouseLeave={() => setAt(null)}
      >
        <path d={drawn.d} className="be-chart-line" vectorEffect="non-scaling-stroke" />
        {x !== null && <line x1={x} x2={x} y1={0} y2={CHART_H} className="be-chart-cursor" vectorEffect="non-scaling-stroke" />}
      </svg>
      <div className="be-chart-axis">
        <span>{shortTime(value.t[0])}</span>
        <span>{t("{count} values", { count: value.count })}</span>
        <span>{shortTime(value.t[value.t.length - 1])}</span>
      </div>
    </div>
  );
}

function StateStrip({ value }: { value: SampledTrace }) {
  const runs = stateRuns(value.v);
  const names = [...new Set(runs.map((run) => run.value))];
  return (
    <div className="be-chart">
      <div className="be-chart-head"><b>{String(value.last ?? "—")}</b><small>{t("{count} values", { count: value.count })}</small></div>
      <div className="be-state-strip">
        {runs.map((run) => (
          <span key={run.start} className={`be-state-run be-state-${names.indexOf(run.value) % 6}`} style={{ left: `${run.start * 100}%`, width: `${run.share * 100}%` }} title={run.value} />
        ))}
      </div>
      <div className="be-chart-axis">
        <span>{shortTime(value.t[0])}</span>
        <span className="be-state-legend">{names.slice(0, 6).map((name, index) => <span key={name}><i className={`be-state-${index}`} />{name}</span>)}</span>
        <span>{shortTime(value.t[value.t.length - 1])}</span>
      </div>
    </div>
  );
}

/** One value a test run carried, drawn for its type: a chart, a mode strip, a number or a verdict. */
function TraceView({ value, unit }: { value: TraceValue; unit: string }) {
  switch (value.type) {
    case "series":
      return <SeriesChart value={value} unit={unit} />;
    case "state":
      return <StateStrip value={value} />;
    case "number":
      return <p className="be-trace-number"><b>{number(value.value)}</b>{unit && <small> {unit}</small>}</p>;
    case "result":
      return (
        <p className={`be-tip-verdict be-status-${value.status}`}>
          <i className={`be-light be-status-${value.status}`} />
          {value.value !== null && <b>{number(value.value)}</b>}
          <span>{value.message || value.status}</span>
        </p>
      );
    case "missing":
      return <p className="be-trace-empty">{value.reason}</p>;
    default:
      return <p className="be-trace-empty">—</p>;
  }
}

/** The inspector's "Last test": what entered the block on each wire and what left it. */
function TestRun({ node, spec }: { node: DiagramNode; spec: BlockSpec }) {
  const { blocks, diagram, trace } = useEditor();
  if (!trace) return null;
  const nodes = Object.fromEntries(diagram.nodes.map((item) => [item.id, item]));
  const entering = spec.inputs.flatMap((port) =>
    inputTraces(diagram, trace, node.id, port.port).map(({ source, value }) => {
      const from = nodes[source.source];
      const out = from && blocks[from.block]?.outputs.find((item) => item.port === source.source_port);
      return { key: `${port.port}-${edgeKey(source)}`, port, value, from: from ? `${nodeLabel(from, blocks)} › ${out?.label ?? source.source_port}` : source.source };
    }),
  );
  const leaving = spec.outputs.flatMap((port) => {
    const value = trace[node.id]?.[port.port];
    return value ? [{ port, value }] : [];
  });
  if (!entering.length && !leaving.length) return null;
  return (
    <section className="be-test-run">
      <h4>{t("Last test")}</h4>
      {entering.length > 0 && <h5>{t("In")}</h5>}
      {entering.map(({ key, port, value, from }) => (
        <div className="be-trace" key={key}>
          <strong><i className={`be-swatch be-type-${port.type}`} />{port.label}<small>← {from}</small></strong>
          <TraceView value={value} unit={port.unit} />
        </div>
      ))}
      {leaving.length > 0 && <h5>{t("Out")}</h5>}
      {leaving.map(({ port, value }) => (
        <div className="be-trace" key={port.port}>
          <strong><i className={`be-swatch be-type-${port.type}`} />{port.label}</strong>
          <TraceView value={value} unit={port.unit} />
        </div>
      ))}
    </section>
  );
}

function Inspector({
  node,
  readOnly,
  onChange,
  blockHref,
  tools,
}: {
  node: DiagramNode;
  readOnly: boolean;
  onChange: (next: Diagram) => void;
  blockHref?: (blockId: string) => string;
  tools?: (node: DiagramNode) => ReactNode;
}) {
  const { blocks, diagram, check } = useEditor();
  const spec = blocks[node.block];
  const [label, setLabel] = useState(node.label ?? "");
  useEffect(() => setLabel(node.label ?? ""), [node.id, node.label]);
  if (!spec) return <div className="be-inspector-body"><p className="be-issue">{t("This block is not in the catalog.")}</p></div>;
  const issues = check?.node_errors?.[node.id] ?? [];
  const warnings = check?.node_warnings?.[node.id] ?? [];
  const recorded = new Set(node.record ?? []);
  const wiredFrom = (port: string) =>
    diagram.edges
      .filter((edge) => edge.target === node.id && edge.target_port === port)
      .map((edge) => {
        const source = diagram.nodes.find((item) => item.id === edge.source);
        const out = source && blocks[source.block]?.outputs.find((item) => item.port === edge.source_port);
        return source ? `${nodeLabel(source, blocks)} › ${out?.label ?? edge.source_port}` : edge.source;
      });
  return (
    <div className="be-inspector-body">
      <div className="be-inspector-head">
        <span className="be-eyebrow">{spec.group || spec.library}</span>
        <input
          className="be-label-input"
          value={label}
          placeholder={spec.name}
          disabled={readOnly}
          aria-label={t("Name on the diagram")}
          onChange={(event) => setLabel(event.target.value)}
          onBlur={() => onChange(updateNode(diagram, node.id, (item) => ({ ...item, label: label.trim() || undefined })))}
        />
        <p>{spec.summary}</p>
        <code>{node.id} · {spec.block_id}</code>
        {blockHref && <a href={blockHref(spec.block_id)} target="_blank" rel="noreferrer">{t("Open the block's page")}</a>}
      </div>
      {(issues.length > 0 || warnings.length > 0) && (
        <ul className="be-problems">
          {issues.map((item) => <li key={item} className="be-issue"><AlertTriangle size={12} /> {item}</li>)}
          {warnings.map((item) => <li key={item} className="be-warning">{item}</li>)}
        </ul>
      )}
      {tools && <div className="be-inspector-tools">{tools(node)}</div>}
      <TestRun node={node} spec={spec} />
      {spec.parameters.length > 0 && (
        <section>
          <h4>{t("Parameters")}</h4>
          {spec.parameters.map((parameter) => (
            <ParameterField
              key={parameter.name}
              node={node}
              parameter={parameter}
              readOnly={readOnly}
              onSet={(value) => onChange(setParameter(diagram, node.id, parameter.name, value))}
            />
          ))}
        </section>
      )}
      {spec.inputs.length > 0 && (
        <section>
          <h4>{t("Inputs")}</h4>
          {spec.inputs.map((port) => {
            const sources = wiredFrom(port.port);
            return (
              <div className="be-port-doc" key={port.port}>
                <strong><i className={`be-swatch be-type-${port.type}`} />{port.label}</strong>
                <small>
                  {port.types.map(typeLabel).join(" / ")}
                  {port.unit ? ` · ${port.unit}` : ""}
                  {port.required ? ` · ${t("required")}` : ` · ${t("optional")}`}
                  {port.multiple ? ` · ${t("any number of wires")}` : ""}
                </small>
                <p>{port.description}</p>
                <p className={sources.length ? "be-wired" : port.required ? "be-unwired" : "be-wired"}>
                  {sources.length ? `← ${sources.join(", ")}` : port.required ? t("Not wired") : t("Not wired (optional)")}
                </p>
              </div>
            );
          })}
        </section>
      )}
      {spec.outputs.length > 0 && (
        <section>
          <h4>{t("Outputs")}</h4>
          {spec.outputs.map((port) => {
            return (
              <div className="be-port-doc" key={port.port}>
                <strong><i className={`be-swatch be-type-${port.type}`} />{port.label}</strong>
                <small>{typeLabel(port.type)}{port.unit ? ` · ${port.unit}` : ""}</small>
                <p>{port.description}</p>
                {RECORDABLE.has(port.type) && (
                  <label className="be-record">
                    <input type="checkbox" checked={recorded.has(port.port)} disabled={readOnly} onChange={() => onChange(toggleRecord(diagram, node.id, port.port))} />
                    <Database size={12} /> {t("Record in the historian")}
                  </label>
                )}
              </div>
            );
          })}
        </section>
      )}
      <section className="be-docs">
        <h4>{t("What it does")}</h4>
        <p>{spec.description}</p>
        <h4>{t("How to read it")}</h4>
        <p>{spec.reading}</p>
        {spec.assumptions.length > 0 && <><h4>{t("Assumptions")}</h4><ul>{spec.assumptions.map((item) => <li key={item}>{item}</li>)}</ul></>}
        {spec.limitations.length > 0 && <><h4>{t("Limitations")}</h4><ul>{spec.limitations.map((item) => <li key={item}>{item}</li>)}</ul></>}
        {spec.formula && <><h4>{t("Formula")}</h4><code className="be-formula">{spec.formula}</code></>}
        {spec.references.length > 0 && <><h4>{t("References")}</h4><div className="be-references">{renderMarkdown(spec.references.map((item) => `- ${item}`).join("\n"))}</div></>}
      </section>
    </div>
  );
}

function CheckSummary({ onSelect }: { onSelect: (id: string) => void }) {
  const { check, diagram, blocks } = useEditor();
  // A valid diagram says so in the toolbar's small mark; the panel speaks only of problems and
  // warnings (round 9: "The diagram is valid" took the page's room).
  if (!check || (check.valid && !check.warnings.length)) return null;
  const nodes = Object.fromEntries(diagram.nodes.map((node) => [node.id, node]));
  const located = Object.entries(check.node_errors ?? {}).flatMap(([id, items]) => items.map((item) => ({ id, item })));
  const general = check.errors.filter((item) => !located.some((entry) => entry.item === item));
  return (
    <div className={`be-check ${check.valid ? "be-check-ok" : "be-check-bad"}`}>
      <strong>{check.valid ? <><CheckCircle2 size={14} /> {t("The diagram is valid")}</> : <><AlertTriangle size={14} /> {t("{count} problems", { count: check.errors.length })}</>}</strong>
      {(general.length > 0 || located.length > 0) && (
        <ul>
          {general.map((item) => <li key={item}>{item}</li>)}
          {located.map(({ id, item }) => (
            <li key={`${id}-${item}`}>
              <button type="button" onClick={() => onSelect(id)}>{nodes[id] ? nodeLabel(nodes[id], blocks) : id}</button> {item}
            </li>
          ))}
        </ul>
      )}
      {check.warnings.length > 0 && <ul className="be-check-warnings">{check.warnings.map((item) => <li key={item}>{item}</li>)}</ul>}
    </div>
  );
}

// --- the palette -----------------------------------------------------------------------------

const DRAG_TYPE = "application/x-processcraft-block";

function Palette({ catalog, onAdd, readOnly, searchRef }: { catalog: BlockCatalog; onAdd: (block: string) => void; readOnly: boolean; searchRef: { current: HTMLInputElement | null } }) {
  const [search, setSearch] = useState("");
  // One library open at a time, none at first; a search opens every library it finds blocks in.
  const [open, setOpen] = useState<string | null>(null);
  const { libraryIndex } = useEditor();
  const groups = palette(catalog, search);
  const searching = search.trim() !== "";
  return (
    <aside className="be-palette" aria-label={t("Blocks")}>
      <div className="be-palette-head">
        <strong>{t("Add a block")}</strong>
        <small>{t("Click one to add it, or drag it onto the diagram.")}</small>
      </div>
      <label className="be-search">
        <Search size={14} />
        <input ref={searchRef} value={search} placeholder={t("Search blocks")} aria-label={t("Search blocks")} onChange={(event) => setSearch(event.target.value)} />
      </label>
      {groups.map(({ library, blocks }) => {
        const expanded = searching || open === library.library;
        const panel = `be-lib-panel-${library.library}`;
        return (
          <section key={library.library} className={expanded ? "be-lib-open" : undefined}>
            <button
              type="button"
              className="be-lib-toggle"
              aria-expanded={expanded}
              aria-controls={panel}
              title={library.description}
              disabled={searching}
              onClick={() => setOpen((current) => (current === library.library ? null : library.library))}
            >
              <ChevronRight size={14} className="be-chevron" />
              <i className={`be-lib-dot be-lib-${libraryIndex[library.library] ?? 0}`} />
              <span>{library.name}</span>
              <small>{blocks.length}</small>
            </button>
            {expanded && (
              <div id={panel} className="be-lib-blocks">
                {blocks.map((block) => (
                  <button
                    type="button"
                    key={block.block_id}
                    className={`be-palette-item be-lib-${libraryIndex[library.library] ?? 0}`}
                    draggable={!readOnly}
                    disabled={readOnly}
                    title={`${block.summary}\n${t("Drag onto the diagram, or click to add it.")}`}
                    onDragStart={(event: DragEvent) => {
                      event.dataTransfer.setData(DRAG_TYPE, block.block_id);
                      event.dataTransfer.effectAllowed = "move";
                    }}
                    onClick={() => onAdd(block.block_id)}
                  >
                    {block.image && <img className="be-palette-image" src={block.image} alt="" draggable={false} loading="lazy" />}
                    <span className="be-palette-text">
                      <strong>{block.name}</strong>
                      <small>{block.summary}</small>
                    </span>
                  </button>
                ))}
              </div>
            )}
          </section>
        );
      })}
      {!groups.length && <p className="be-empty">{t("No block matches.")}</p>}
    </aside>
  );
}

// --- the editor ------------------------------------------------------------------------------

function isTyping(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null;
  return Boolean(element && (element.tagName === "INPUT" || element.tagName === "TEXTAREA" || element.tagName === "SELECT" || element.isContentEditable));
}

function Editor(props: BlockEditorProps) {
  const { catalog, check, trace, title, actions, aside, blockHref, inspectorTools } = props;
  const readOnly = Boolean(props.readOnly || !props.onChange);
  const blocks = useMemo(() => byId(catalog), [catalog]);
  const libraryIndex = useMemo(() => Object.fromEntries(catalog.libraries.map((item, index) => [item.library, index])), [catalog]);
  // The legend names what the catalog's wires carry: Link's four kinds, Models' real signals.
  const legend = useMemo(() => {
    const used = new Set(catalog.blocks.flatMap((block) => [...block.inputs, ...block.outputs].map((port) => port.type)));
    return ["series", "state", "number", "result", "intervals", "real"].filter((type) => used.has(type));
  }, [catalog]);
  const [history, setHistory] = useState<History>(() => startHistory(props.diagram));
  const [selected, setSelected] = useState<string[]>([]);
  const [selectedEdges, setSelectedEdges] = useState<string[]>([]);
  const [connecting, setConnecting] = useState<Connecting>(null);
  const [refusal, setRefusal] = useState("");
  // A test run's values on the wires: off at first, since on a full diagram they crowd it.
  const [showValues, setShowValues] = useState(false);
  const clip = useRef<Clip | null>(null);
  const paletteSearch = useRef<HTMLInputElement | null>(null);
  const flow = useReactFlow();
  const diagram = history.present;

  // A diagram the app loads (another algorithm, a reload) starts a new history.
  useEffect(() => {
    setHistory((current) => (current.present === props.diagram ? current : startHistory(props.diagram)));
  }, [props.diagram]);

  const commit = useCallback(
    (next: Diagram) => {
      if (readOnly || next === diagram) return;
      setHistory((current) => record(current, next));
      props.onChange?.(next);
    },
    [diagram, props, readOnly],
  );
  const travel = useCallback(
    (move: (history: History) => History) => {
      const next = move(history);
      if (next === history) return;
      setHistory(next);
      props.onChange?.(next.present);
    },
    [history, props],
  );

  const [nodes, setNodes] = useState<BlockFlowNode[]>([]);
  useEffect(() => {
    const chosen = new Set(selected);
    setNodes(
      diagram.nodes.map((node) => ({
        id: node.id,
        type: "block",
        position: { x: node.x ?? 0, y: node.y ?? 0 },
        data: { node },
        selected: chosen.has(node.id),
        draggable: !readOnly,
      })),
    );
  }, [diagram, selected, readOnly]);

  const edges: Edge[] = useMemo(() => {
    const byNode = Object.fromEntries(diagram.nodes.map((node) => [node.id, node]));
    const chosen = new Set(selectedEdges);
    return diagram.edges.map((edge) => {
      const source = blocks[byNode[edge.source]?.block ?? ""]?.outputs.find((port) => port.port === edge.source_port);
      const type = source?.type ?? "series";
      const key = edgeKey(edge);
      const value = trace?.[edge.source]?.[edge.source_port];
      return {
        id: key,
        source: edge.source,
        sourceHandle: edge.source_port,
        target: edge.target,
        targetHandle: edge.target_port,
        className: `be-edge be-type-${type}${value?.type === "missing" ? " be-edge-missing" : ""}`,
        selected: chosen.has(key),
        label: showValues && value ? traceText(value, uiLocale()) : undefined,
        labelBgPadding: [4, 2] as [number, number],
        labelBgBorderRadius: 3,
      };
    });
  }, [diagram, blocks, trace, selectedEdges, showValues]);

  const rules = useMemo(() => ({ loops: Boolean(props.allowLoops) }), [props.allowLoops]);
  const compatible = useMemo(() => (connecting ? compatiblePorts(diagram, blocks, connecting, rules) : null), [connecting, diagram, blocks, rules]);

  const onNodesChange = useCallback(
    (changes: NodeChange<BlockFlowNode>[]) => {
      setNodes((current) => applyNodeChanges(changes, current));
      const selection = changes.filter((change) => change.type === "select");
      if (selection.length) {
        setSelected((current) => {
          const next = new Set(current);
          for (const change of selection) if (change.type === "select") (change.selected ? next.add(change.id) : next.delete(change.id));
          return [...next];
        });
      }
    },
    [],
  );

  const addAt = useCallback(
    (block: string, at?: { x: number; y: number }) => {
      if (readOnly) return;
      const center = at ?? flow.screenToFlowPosition({ x: window.innerWidth / 2, y: window.innerHeight / 2 });
      const added = addNode(diagram, blocks, block, { x: center.x - 90, y: center.y - 40 });
      commit(added.diagram);
      setSelected([added.id]);
    },
    [blocks, commit, diagram, flow, readOnly],
  );

  const deleteSelection = useCallback(() => {
    if (readOnly) return;
    let next = diagram;
    if (selected.length) next = removeNodes(next, selected);
    if (selectedEdges.length) next = removeEdges(next, selectedEdges);
    commit(next);
    setSelected([]);
    setSelectedEdges([]);
  }, [commit, diagram, readOnly, selected, selectedEdges]);

  const copySelection = useCallback(() => {
    if (selected.length) clip.current = copy(diagram, selected);
  }, [diagram, selected]);

  const pasteClip = useCallback(() => {
    if (readOnly || !clip.current?.nodes.length) return;
    const pasted = paste(diagram, clip.current);
    commit(pasted.diagram);
    setSelected(pasted.ids);
    clip.current = copy(pasted.diagram, pasted.ids);
  }, [commit, diagram, readOnly]);

  const arrangeAll = useCallback(() => {
    commit(arrange(diagram));
    window.setTimeout(() => flow.fitView({ padding: 0.15, duration: 250 }), 30);
  }, [commit, diagram, flow]);

  const onKeyDown = (event: KeyboardEvent) => {
    if (isTyping(event.target)) return;
    const mod = event.ctrlKey || event.metaKey;
    const key = event.key.toLowerCase();
    if (mod && key === "z" && !event.shiftKey) { event.preventDefault(); travel(undo); }
    else if (mod && (key === "y" || (key === "z" && event.shiftKey))) { event.preventDefault(); travel(redo); }
    else if (mod && key === "c") copySelection();
    else if (mod && key === "v") { event.preventDefault(); pasteClip(); }
    else if (mod && key === "d") { event.preventDefault(); copySelection(); pasteClip(); }
    else if (key === "delete" || key === "backspace") { event.preventDefault(); deleteSelection(); }
  };

  const onConnect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target || !connection.sourceHandle || !connection.targetHandle) return;
      const wire = { source: connection.source, source_port: connection.sourceHandle, target: connection.target, target_port: connection.targetHandle };
      const problem = wireProblem(diagram, blocks, wire, rules);
      if (problem) setRefusal(problem);
      else commit(connect(diagram, blocks, wire, rules));
    },
    [blocks, commit, diagram, rules],
  );

  const onDrop = (event: DragEvent) => {
    const block = event.dataTransfer.getData(DRAG_TYPE);
    if (!block) return;
    event.preventDefault();
    addAt(block, flow.screenToFlowPosition({ x: event.clientX, y: event.clientY }));
  };

  useEffect(() => {
    if (!refusal) return;
    const timer = window.setTimeout(() => setRefusal(""), 4000);
    return () => window.clearTimeout(timer);
  }, [refusal]);

  const one = selected.length === 1 ? diagram.nodes.find((node) => node.id === selected[0]) : undefined;
  const context: EditorContextValue = { blocks, diagram, check, trace, compatible, libraryIndex };

  return (
    <EditorContext.Provider value={context}>
      <div className={`be-editor${readOnly ? " be-readonly" : ""}${props.className ? ` ${props.className}` : ""}`} onKeyDown={onKeyDown} tabIndex={-1}>
        <div className="be-toolbar">
          <div className="be-title">{title ?? <><Workflow size={16} /> {t("Diagram")}</>}</div>
          <div className="be-tools" role="toolbar" aria-label={t("Diagram tools")}>
            {!readOnly && (
              <>
                <button type="button" className="be-tool be-tool-text be-tool-add" title={t("Find a block to add")} onClick={() => paletteSearch.current?.focus()}><Plus size={15} /> {t("Block")}</button>
                <span className="be-sep" />
              </>
            )}
            {/* Read-only (an algorithm's page), the tools that change the diagram are left out, not
                shown disabled (round 9): only fitting the view stays. */}
            {!readOnly && (
              <>
                <button type="button" className="be-tool" title={t("Undo (Ctrl+Z)")} disabled={!history.past.length} onClick={() => travel(undo)}><Undo2 size={15} /></button>
                <button type="button" className="be-tool" title={t("Redo (Ctrl+Shift+Z)")} disabled={!history.future.length} onClick={() => travel(redo)}><Redo2 size={15} /></button>
                <span className="be-sep" />
                <button type="button" className="be-tool" title={t("Copy (Ctrl+C)")} disabled={!selected.length} onClick={copySelection}><Copy size={15} /></button>
                <button type="button" className="be-tool" title={t("Paste (Ctrl+V)")} onClick={pasteClip}><ClipboardPaste size={15} /></button>
                <button type="button" className="be-tool" title={t("Delete (Del)")} disabled={!selected.length && !selectedEdges.length} onClick={deleteSelection}><Trash2 size={15} /></button>
                <span className="be-sep" />
                <button type="button" className="be-tool be-tool-text" title={t("Lay the blocks out from inputs to outputs")} disabled={!diagram.nodes.length} onClick={arrangeAll}><Workflow size={15} /> {t("Arrange")}</button>
              </>
            )}
            <button type="button" className="be-tool" title={t("Fit to screen")} onClick={() => flow.fitView({ padding: 0.15, duration: 250 })}><Maximize size={15} /></button>
            {trace && (
              <>
                <span className="be-sep" />
                <button
                  type="button"
                  className="be-tool be-tool-text"
                  aria-pressed={showValues}
                  title={t("Show what each wire carried in the last test. Select a block to see its inputs and outputs over time.")}
                  onClick={() => setShowValues((now) => !now)}
                >
                  {showValues ? <Eye size={15} /> : <EyeOff size={15} />} {t("Values on wires")}
                </button>
              </>
            )}
          </div>
          {check && (!check.valid || !readOnly) && (
            <span className={`be-status ${check.valid ? "be-status-ok" : "be-status-bad"}`}>
              {check.valid ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />}
              {check.valid ? t("Valid") : t("{count} problems", { count: check.errors.length })}
            </span>
          )}
          <div className="be-actions">{actions}</div>
        </div>
        <div className="be-body">
          {!readOnly && <Palette catalog={catalog} onAdd={(block) => addAt(block)} readOnly={readOnly} searchRef={paletteSearch} />}
          <div className="be-canvas" onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "move"; }} onDrop={onDrop}>
            <ReactFlow<BlockFlowNode, Edge>
              nodes={nodes}
              edges={edges}
              nodeTypes={NODE_TYPES}
              onNodesChange={onNodesChange}
              onEdgesChange={(changes) => {
                const selection = changes.filter((change) => change.type === "select");
                if (selection.length) {
                  setSelectedEdges((current) => {
                    const next = new Set(current);
                    for (const change of selection) if (change.type === "select") (change.selected ? next.add(change.id) : next.delete(change.id));
                    return [...next];
                  });
                }
              }}
              onNodeDragStop={(_event, _node, moved) => commit(moveNodes(diagram, Object.fromEntries(moved.map((item) => [item.id, item.position]))))}
              onConnect={onConnect}
              onConnectStart={(_event, params: OnConnectStartParams) => {
                if (params.nodeId && params.handleId && params.handleType) setConnecting({ node: params.nodeId, port: params.handleId, side: params.handleType });
              }}
              onConnectEnd={() => setConnecting(null)}
              isValidConnection={(connection) =>
                Boolean(connection.sourceHandle && connection.targetHandle) &&
                !wireProblem(diagram, blocks, { source: connection.source, source_port: connection.sourceHandle as string, target: connection.target, target_port: connection.targetHandle as string }, rules)
              }
              onPaneClick={() => { setSelected([]); setSelectedEdges([]); }}
              deleteKeyCode={null}
              nodesConnectable={!readOnly}
              elementsSelectable
              fitView
              fitViewOptions={{ padding: 0.15 }}
              minZoom={0.2}
              maxZoom={2}
              proOptions={{ hideAttribution: true }}
            >
              <Background variant={BackgroundVariant.Dots} gap={18} size={1.2} />
              <Controls showInteractive={false} />
              <MiniMap pannable zoomable nodeClassName={(node) => `be-mini be-lib-${libraryIndex[blocks[(node.data as BlockData).node.block]?.library ?? ""] ?? 0}`} />
            </ReactFlow>
            {refusal && <div className="be-refusal" role="status"><AlertTriangle size={14} /> {refusal}</div>}
            {!diagram.nodes.length && !readOnly && <div className="be-empty-canvas">{t("Drag blocks from the left, then wire an output to an input.")}</div>}
            <div className="be-legend" aria-label={t("What the wires carry")}>
              {legend.map((type) => <span key={type}><i className={`be-swatch be-type-${type}`} />{typeLabel(type)}</span>)}
            </div>
          </div>
          <aside className="be-inspector" aria-label={t("Inspector")}>
            {one ? (
              <Inspector key={one.id} node={one} readOnly={readOnly} onChange={commit} blockHref={blockHref} tools={inspectorTools} />
            ) : selected.length > 1 ? (
              <div className="be-inspector-body">
                <p className="be-multi">{t("{count} blocks selected", { count: selected.length })}</p>
                {!readOnly && <button type="button" className="button button-secondary button-small" onClick={deleteSelection}><Trash2 size={13} /> {t("Delete")}</button>}
              </div>
            ) : (
              <div className="be-inspector-body">
                <CheckSummary onSelect={(id) => setSelected([id])} />
                {aside}
              </div>
            )}
          </aside>
        </div>
      </div>
    </EditorContext.Provider>
  );
}

export function BlockEditor(props: BlockEditorProps) {
  return (
    <ReactFlowProvider>
      <Editor {...props} />
    </ReactFlowProvider>
  );
}

export * from "./blockModel.js";
