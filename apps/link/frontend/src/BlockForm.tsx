/**
 * The form of a block file, in the order a block is thought out (owner, 2026-10-25, round 9):
 * 1 what it is, 2 its inputs, 3 its outputs, 4 its parameters with their defaults, 5 its Python
 * code. Each input, output and parameter is one compact row (name, type, unit, description), its
 * less used fields under it, instead of a wide table. The same form makes a new block (from
 * scratch, from an imported file or from a copy) and the next version of one. It holds every
 * field a block Link ships has (owner D20, 2026-10-26): the other types an input accepts, an
 * output's normal range and which way is good, and whether the block runs without data.
 */
import { BlockImageField } from "@plantcraft/ui";
import "@plantcraft/ui/codeEditor.css";
import { CodeEditor } from "@plantcraft/ui/codeEditor";
import { Plus, Trash2 } from "lucide-react";
import { useMemo, type ReactNode } from "react";
import { newParameter, newPort } from "./blockFile";
import { NewLibraryButton } from "./NewLibrary";
import { t } from "./i18n";
import type { BlockFileDoc, BlockFileParameter, BlockFilePort, FilePortType } from "./types";

const PORT_TYPES: FilePortType[] = ["series", "state", "number", "result", "intervals"];
const TYPE_WORDS: Record<FilePortType, string> = { series: "Series", state: "State", number: "Number", result: "Verdict", intervals: "Intervals" };
const PARAMETER_TYPES: BlockFileParameter["type"][] = ["number", "integer", "boolean", "text", "choice"];

/** Lines of a text area as a list (empty lines dropped). */
const lines = (text: string) => text.split("\n").map((item) => item.trim()).filter(Boolean);
const numberOrNull = (text: string) => (text === "" ? null : Number(text));

/** One numbered part of the form: its title and what it is for, then its fields. */
function Part({ number, title, detail, id, children }: { number: number; title: string; detail?: string; id: string; children: ReactNode }) {
  return <section className="panel blkf-part" id={id} aria-labelledby={`${id}-title`}>
    <header className="blkf-part-head">
      <span className="blkf-part-number pc-num" aria-hidden="true">{number}</span>
      <div><h2 id={`${id}-title`}>{title}</h2>{detail && <p>{detail}</p>}</div>
    </header>
    {children}
  </section>;
}

/** A small labelled field inside a row. */
function Field({ label, className, children }: { label: string; className?: string; children: ReactNode }) {
  return <label className={["blkf-field", className].filter(Boolean).join(" ")}><span>{label}</span>{children}</label>;
}

function PortRows({ kind, ports, readOnly, onChange }: { kind: "input" | "output"; ports: BlockFilePort[]; readOnly: boolean; onChange: (next: BlockFilePort[]) => void }) {
  const set = (index: number, change: Partial<BlockFilePort>) => onChange(ports.map((item, at) => (at === index ? { ...item, ...change } : item)));
  const title = kind === "input" ? t("Inputs") : t("Outputs");
  return <>
    {ports.length > 0 && <ol className="blkf-rows">{ports.map((port, index) => {
      const label = (field: string) => t("{kind} {number}: {field}", { kind: title, number: index + 1, field });
      return <li key={index} className="blkf-row">
        <div className="blkf-row-main blkf-port-main">
          <Field label={t("Port")}><input className="pc-mono" aria-label={label(t("port"))} value={port.port} disabled={readOnly} onChange={(event) => set(index, { port: event.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_") })} /></Field>
          <Field label={t("Label")}><input aria-label={label(t("label"))} value={port.label ?? ""} disabled={readOnly} onChange={(event) => set(index, { label: event.target.value })} /></Field>
          <Field label={t("Type")}><select aria-label={label(t("type"))} value={port.type} disabled={readOnly} onChange={(event) => set(index, { type: event.target.value as FilePortType })}>
            {PORT_TYPES.map((item) => <option key={item} value={item}>{t(TYPE_WORDS[item])}</option>)}
          </select></Field>
          <Field label={t("Unit")}><input aria-label={label(t("unit"))} value={port.unit ?? ""} disabled={readOnly} onChange={(event) => set(index, { unit: event.target.value })} /></Field>
          {!readOnly && <button type="button" className="icon-button blkf-remove" title={t("Remove")} aria-label={t("Remove {port}", { port: port.port })} onClick={() => onChange(ports.filter((_, at) => at !== index))}><Trash2 size={15} /></button>}
        </div>
        <div className="blkf-row-more">
          <Field label={t("Description")} className="blkf-grow"><input aria-label={label(t("description"))} value={port.description ?? ""} disabled={readOnly} onChange={(event) => set(index, { description: event.target.value })} /></Field>
          {kind === "input"
            ? <>
              <label className="blkf-check"><input type="checkbox" aria-label={label(t("required"))} checked={port.required ?? true} disabled={readOnly} onChange={(event) => set(index, { required: event.target.checked })} />{t("Required")}</label>
              <label className="blkf-check"><input type="checkbox" aria-label={label(t("several wires"))} checked={port.multiple ?? false} disabled={readOnly} onChange={(event) => set(index, { multiple: event.target.checked })} />{t("Several wires")}</label>
            </>
            : <label className="blkf-check"><input type="checkbox" aria-label={label(t("recorded in the historian"))} checked={port.record ?? false} disabled={readOnly} onChange={(event) => set(index, { record: event.target.checked })} />{t("Recorded in the Historian")}</label>}
        </div>
        {kind === "input"
          ? <fieldset className="blkf-row-more blkf-also" disabled={readOnly}>
            <legend>{t("Also accepts")}</legend>
            {PORT_TYPES.filter((item) => item !== port.type).map((item) => {
              const also = (port.types ?? []).includes(item);
              return <label key={item} className="blkf-check"><input type="checkbox" aria-label={label(t("also accepts {type}", { type: t(TYPE_WORDS[item]) }))} checked={also}
                onChange={(event) => set(index, { types: event.target.checked ? [...new Set([port.type, ...(port.types ?? []), item])] : (port.types ?? []).filter((other) => other !== item) })} />{t(TYPE_WORDS[item])}</label>;
            })}
          </fieldset>
          : (port.type === "number" || port.type === "series") && <div className="blkf-row-more">
            <Field label={t("Normal from")} className="blkf-limit"><input type="number" aria-label={label(t("normal low"))} value={port.low ?? ""} disabled={readOnly} onChange={(event) => set(index, { low: numberOrNull(event.target.value) })} /></Field>
            <Field label={t("Normal to")} className="blkf-limit"><input type="number" aria-label={label(t("normal high"))} value={port.high ?? ""} disabled={readOnly} onChange={(event) => set(index, { high: numberOrNull(event.target.value) })} /></Field>
            <Field label={t("Better when")}><select aria-label={label(t("better when"))} value={port.better ?? ""} disabled={readOnly} onChange={(event) => set(index, { better: (event.target.value || null) as BlockFilePort["better"] })}>
              <option value="">{t("Neither")}</option><option value="higher">{t("Higher")}</option><option value="lower">{t("Lower")}</option>
            </select></Field>
          </div>}
      </li>;
    })}</ol>}
    {!ports.length && <p className="muted small">{kind === "input" ? t("No inputs: the block reads nothing from other blocks.") : t("A block gives at least one output.")}</p>}
    {!readOnly && <button type="button" className="button button-secondary button-small blkf-add" onClick={() => onChange([...ports, newPort(kind, ports.map((item) => item.port))])}><Plus size={15} />{kind === "input" ? t("Add an input") : t("Add an output")}</button>}
  </>;
}

function DefaultField({ parameter, readOnly, label, onChange }: { parameter: BlockFileParameter; readOnly: boolean; label: string; onChange: (value: unknown) => void }) {
  if (parameter.type === "boolean") return <input type="checkbox" aria-label={label} checked={Boolean(parameter.default)} disabled={readOnly} onChange={(event) => onChange(event.target.checked)} />;
  if (parameter.type === "choice") {
    return <select aria-label={label} value={String(parameter.default ?? "")} disabled={readOnly} onChange={(event) => onChange(event.target.value)}>
      {(parameter.choices ?? []).map((item) => <option key={item} value={item}>{item}</option>)}
    </select>;
  }
  if (parameter.type === "text") return <input aria-label={label} value={String(parameter.default ?? "")} disabled={readOnly} onChange={(event) => onChange(event.target.value)} />;
  return <input type="number" aria-label={label} step={parameter.type === "integer" ? 1 : "any"} value={parameter.default === null || parameter.default === undefined ? "" : String(parameter.default)} disabled={readOnly}
    onChange={(event) => onChange(event.target.value === "" ? null : parameter.type === "integer" ? Math.round(Number(event.target.value)) : Number(event.target.value))} />;
}

function ParameterRows({ parameters, readOnly, onChange }: { parameters: BlockFileParameter[]; readOnly: boolean; onChange: (next: BlockFileParameter[]) => void }) {
  const set = (index: number, change: Partial<BlockFileParameter>) => onChange(parameters.map((item, at) => (at === index ? { ...item, ...change } : item)));
  return <>
    {parameters.length > 0 && <ol className="blkf-rows">{parameters.map((item, index) => {
      const label = (field: string) => t("Parameter {name}: {field}", { name: item.name || index + 1, field });
      const numeric = item.type === "number" || item.type === "integer";
      return <li key={index} className="blkf-row">
        <div className="blkf-row-main blkf-param-main">
          <Field label={t("Name")}><input className="pc-mono" aria-label={label(t("name"))} value={item.name} disabled={readOnly} onChange={(event) => set(index, { name: event.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_") })} /></Field>
          <Field label={t("Title")}><input aria-label={label(t("title"))} value={item.title ?? ""} disabled={readOnly} onChange={(event) => set(index, { title: event.target.value })} /></Field>
          <Field label={t("Type")}><select aria-label={label(t("type"))} value={item.type} disabled={readOnly} onChange={(event) => {
            const type = event.target.value as BlockFileParameter["type"];
            set(index, { type, default: type === "boolean" ? false : type === "text" ? "" : type === "choice" ? (item.choices ?? [])[0] ?? "" : 0 });
          }}>{PARAMETER_TYPES.map((kind) => <option key={kind} value={kind}>{t(kind)}</option>)}</select></Field>
          <Field label={t("Default")}><DefaultField parameter={item} readOnly={readOnly} label={label(t("default"))} onChange={(value) => set(index, { default: value })} /></Field>
          <Field label={t("Unit")}><input aria-label={label(t("unit"))} value={item.unit ?? ""} disabled={readOnly} onChange={(event) => set(index, { unit: event.target.value })} /></Field>
          {!readOnly && <button type="button" className="icon-button blkf-remove" title={t("Remove")} aria-label={t("Remove {port}", { port: item.name })} onClick={() => onChange(parameters.filter((_, at) => at !== index))}><Trash2 size={15} /></button>}
        </div>
        <div className="blkf-row-more">
          <Field label={t("Description")} className="blkf-grow"><input aria-label={label(t("description"))} value={item.description ?? ""} disabled={readOnly} onChange={(event) => set(index, { description: event.target.value })} /></Field>
          {numeric && <Field label={t("Minimum")} className="blkf-limit"><input type="number" aria-label={label(t("minimum"))} value={item.minimum ?? ""} disabled={readOnly} onChange={(event) => set(index, { minimum: event.target.value === "" ? null : Number(event.target.value) })} /></Field>}
          {numeric && <Field label={t("Maximum")} className="blkf-limit"><input type="number" aria-label={label(t("maximum"))} value={item.maximum ?? ""} disabled={readOnly} onChange={(event) => set(index, { maximum: event.target.value === "" ? null : Number(event.target.value) })} /></Field>}
          {item.type === "choice" && <Field label={t("Choices")} className="blkf-grow"><input aria-label={label(t("choices"))} placeholder={t("choices, separated by commas")} value={(item.choices ?? []).join(", ")} disabled={readOnly}
            onChange={(event) => set(index, { choices: event.target.value.split(",").map((value) => value.trim()).filter(Boolean) })} /></Field>}
        </div>
      </li>;
    })}</ol>}
    {!parameters.length && <p className="muted small">{t("No parameters.")}</p>}
    {!readOnly && <button type="button" className="button button-secondary button-small blkf-add" onClick={() => onChange([...parameters, newParameter(parameters.map((item) => item.name))])}><Plus size={15} />{t("Add a parameter")}</button>}
  </>;
}

export type FormLibrary = { library: string; name: string };

/** The whole block file as a form. `fixedLibrary`: a new version stays in its block's library;
 * `onNewLibrary`, a library made from the form (round 10), which the block then joins. */
export function BlockForm({ file, libraries, problems, readOnly = false, fixedLibrary = false, onChange, onSave, onNewLibrary }: {
  file: BlockFileDoc; libraries: FormLibrary[]; problems: string[]; readOnly?: boolean; fixedLibrary?: boolean;
  onChange: (next: BlockFileDoc) => void; onSave?: () => void; onNewLibrary?: (library: FormLibrary) => void;
}) {
  const docs = file.docs;
  const setDocs = (change: Partial<BlockFileDoc["docs"]>) => onChange({ ...file, docs: { ...docs, ...change } });
  const codeProblems = useMemo(() => problems.filter((item) => /^Line \d+:/.test(item)), [problems]);
  return <div className="blkf">
    <Part number={1} id="blkf-about" title={t("What it is")} detail={t("Its name, the library it sits in (in the palette too), and how it works: people and the assistant read the same text.")}>
      <div className="form-grid">
        <label>{t("Name")}<input id="blkf-name" value={file.name} required disabled={readOnly} onChange={(event) => onChange({ ...file, name: event.target.value })} placeholder={t("UA fouling trend")} /></label>
        <div className="blkf-library">
          <label>{t("Library")}<select id="blkf-library" value={file.library} disabled={readOnly || fixedLibrary} onChange={(event) => onChange({ ...file, library: event.target.value, block_id: file.block_id && !fixedLibrary ? "" : file.block_id })}>
            {libraries.map((item) => <option key={item.library} value={item.library}>{item.name}</option>)}
          </select></label>
          {onNewLibrary && !readOnly && !fixedLibrary && <NewLibraryButton className="button button-secondary button-small" onMade={(made) => { onNewLibrary(made); onChange({ ...file, library: made.library, block_id: "" }); }} />}
        </div>
        <label>{t("Labels")}<input id="blkf-tags" value={(file.tags ?? []).join(", ")} disabled={readOnly} onChange={(event) => onChange({ ...file, tags: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} placeholder={t("fouling, heat exchanger")} /></label>
        <label className="blkf-wide">{t("Summary: what it measures and when to use it (one sentence)")}<input id="blkf-summary" value={docs.summary} required disabled={readOnly} onChange={(event) => setDocs({ summary: event.target.value })} /></label>
        <label className="blkf-wide">{t("How it works")}<textarea id="blkf-description" rows={3} value={docs.description ?? ""} disabled={readOnly} onChange={(event) => setDocs({ description: event.target.value })} /></label>
      </div>
      <div className="blkf-image">
        <span className="blkf-image-label">{t("Image (optional): drawn in the block, as in Simulink")}</span>
        <BlockImageField id="blkf-image" value={file.image ?? ""} disabled={readOnly} onChange={(image) => onChange({ ...file, image })} />
      </div>
      <details className="blkf-details">
        <summary>{t("More about it: how to read it, formula, assumptions, limitations, references")}</summary>
        <div className="form-grid">
          <label>{t("How to read it: what ok, warning and bad mean")}<textarea id="blkf-reading" rows={3} value={docs.reading ?? ""} disabled={readOnly} onChange={(event) => setDocs({ reading: event.target.value })} /></label>
          <label>{t("Formula")}<textarea id="blkf-formula" rows={3} className="pc-mono" value={docs.formula ?? ""} disabled={readOnly} onChange={(event) => setDocs({ formula: event.target.value })} /></label>
          <label>{t("Assumptions (one per line)")}<textarea id="blkf-assumptions" rows={2} value={(docs.assumptions ?? []).join("\n")} disabled={readOnly} onChange={(event) => setDocs({ assumptions: lines(event.target.value) })} /></label>
          <label>{t("Limitations (one per line)")}<textarea id="blkf-limitations" rows={2} value={(docs.limitations ?? []).join("\n")} disabled={readOnly} onChange={(event) => setDocs({ limitations: lines(event.target.value) })} /></label>
          <label className="blkf-wide">{t("References (one per line: author, title, year)")}<textarea id="blkf-references" rows={2} value={(docs.references ?? []).join("\n")} disabled={readOnly} onChange={(event) => setDocs({ references: lines(event.target.value) })} /></label>
        </div>
      </details>
    </Part>
    <Part number={2} id="blkf-inputs" title={t("Inputs")} detail={t("What the block reads from other blocks. A wire joins an output to an input of the same type.")}>
      <PortRows kind="input" ports={file.inputs} readOnly={readOnly} onChange={(inputs) => onChange({ ...file, inputs })} />
      {file.inputs.length > 0 && <label className="blkf-check blkf-missing"><input id="blkf-runs-on-missing" type="checkbox" checked={file.runs_on_missing ?? false} disabled={readOnly} onChange={(event) => onChange({ ...file, runs_on_missing: event.target.checked })} />
        {t("Runs when an input has no data: the code receives NoData and decides (otherwise the block passes NoData on to its outputs)")}</label>}
    </Part>
    <Part number={3} id="blkf-outputs" title={t("Outputs")} detail={t("What it gives: series, states, numbers or a result. A recorded output goes to the Historian when a monitor runs it.")}>
      <PortRows kind="output" ports={file.outputs} readOnly={readOnly} onChange={(outputs) => onChange({ ...file, outputs })} />
    </Part>
    <Part number={4} id="blkf-parameters" title={t("Parameters")} detail={t("The settings people can change, with their defaults; an algorithm can change them on its own block.")}>
      <ParameterRows parameters={file.parameters} readOnly={readOnly} onChange={(parameters) => onChange({ ...file, parameters })} />
    </Part>
    <Part number={5} id="blkf-code" title={t("Code")} detail={t("run(inputs, params, ctx) returns a dict with a value per output port. inputs[port] is a pandas Series (or a number, a result); params.name reads a parameter; ctx.state is the block's memory between runs. Return Result(status, score, message) for a result and NoData(reason) when the block cannot judge.")}>
      <CodeEditor value={file.code} readOnly={readOnly} problems={codeProblems} label={t("Block code")} onChange={(code) => onChange({ ...file, code })} onSave={onSave} />
    </Part>
  </div>;
}
