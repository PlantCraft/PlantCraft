/**
 * `@plantcraft/ui/blockParameter`: one parameter of a block, as the block editor's inspector edits
 * it, and the label of a port type. A subpath of its own, so a page that only shows parameters
 * (an app's schedule or block page) does not load the editor and React Flow (~205 KB).
 */
import { RotateCcw } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { parameterValue, type DiagramNode, type ParameterSpec } from "./blockModel.js";
import { t } from "./i18n.js";

const TYPE_LABELS: Record<string, string> = {
  series: "Signal",
  state: "Mode",
  number: "Number",
  result: "Verdict",
  intervals: "Intervals",
  real: "Real",
};

export function typeLabel(type: string): string {
  return t(TYPE_LABELS[type] ?? type);
}

function schemaType(parameter: ParameterSpec): string {
  const schema = parameter.schema as { type?: string; enum?: unknown[]; anyOf?: { type?: string }[]; items?: { type?: string } };
  if (schema.enum) return "enum";
  const type = schema.type ?? schema.anyOf?.find((item) => item.type && item.type !== "null")?.type;
  if (type === "array" && schema.items?.type === "string") return "strings";
  // Objects and other arrays (a calibration, a table) are edited as JSON text.
  if (!type || type === "object" || type === "array") return "json";
  return type;
}

/** One parameter of a block in a diagram, as the inspector edits it; an app's own page (Link's
 * Inputs and parameters tab) uses the same field outside the editor. */
export function ParameterField({ node, parameter, onSet, readOnly }: { node: DiagramNode; parameter: ParameterSpec; onSet: (value: unknown) => void; readOnly: boolean }) {
  const value = parameterValue(node, parameter);
  const own = node.parameters?.[parameter.name] !== undefined;
  const kind = schemaType(parameter);
  const schema = parameter.schema as { enum?: unknown[]; minimum?: number; maximum?: number; exclusiveMinimum?: number; exclusiveMaximum?: number };
  const [text, setText] = useState(() => (kind === "json" ? JSON.stringify(value ?? null) : kind === "strings" ? ((value as string[] | null) ?? []).join(", ") : String(value ?? "")));
  useEffect(() => {
    setText(kind === "json" ? JSON.stringify(value ?? null) : kind === "strings" ? ((value as string[] | null) ?? []).join(", ") : String(value ?? ""));
  }, [kind, value]);
  const id = `be-p-${node.id}-${parameter.name}`;
  let field: ReactNode;
  if (kind === "enum") {
    field = (
      <select id={id} value={String(value ?? "")} disabled={readOnly} onChange={(event) => onSet(event.target.value)}>
        {(schema.enum ?? []).map((item) => <option key={String(item)} value={String(item)}>{String(item)}</option>)}
      </select>
    );
  } else if (kind === "boolean") {
    field = <input id={id} type="checkbox" checked={Boolean(value)} disabled={readOnly} onChange={(event) => onSet(event.target.checked)} />;
  } else if (kind === "number" || kind === "integer") {
    field = (
      <input
        id={id}
        type="number"
        inputMode="decimal"
        value={text}
        step={kind === "integer" ? 1 : "any"}
        min={schema.minimum ?? schema.exclusiveMinimum}
        max={schema.maximum ?? schema.exclusiveMaximum}
        disabled={readOnly}
        placeholder={parameter.default === null || parameter.default === undefined ? t("empty") : String(parameter.default)}
        onChange={(event) => setText(event.target.value)}
        onBlur={() => {
          if (text.trim() === "") onSet(parameter.default === null ? null : undefined);
          else if (!Number.isNaN(Number(text))) onSet(kind === "integer" ? Math.round(Number(text)) : Number(text));
        }}
      />
    );
  } else if (kind === "string") {
    field = <input id={id} value={text} disabled={readOnly} onChange={(event) => setText(event.target.value)} onBlur={() => onSet(text)} />;
  } else if (kind === "strings") {
    field = (
      <input
        id={id}
        value={text}
        disabled={readOnly}
        onChange={(event) => setText(event.target.value)}
        onBlur={() => onSet(text.split(",").map((item) => item.trim()).filter(Boolean))}
      />
    );
  } else {
    field = (
      <textarea
        id={id}
        value={text}
        rows={2}
        disabled={readOnly}
        onChange={(event) => setText(event.target.value)}
        onBlur={() => {
          try {
            onSet(JSON.parse(text));
          } catch {
            setText(JSON.stringify(value ?? null));
          }
        }}
      />
    );
  }
  return (
    <div className={`be-field${own ? " be-field-own" : ""}`}>
      <label htmlFor={id}>
        {parameter.title}
        {parameter.unit && <small> ({parameter.unit})</small>}
      </label>
      <div className="be-field-control">
        {field}
        {own && !readOnly && (
          <button type="button" className="be-icon-button" title={t("Back to the default")} onClick={() => onSet(undefined)}>
            <RotateCcw size={12} />
          </button>
        )}
      </div>
      {parameter.description && <p>{parameter.description}</p>}
    </div>
  );
}
