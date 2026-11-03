/** Block files (`plantcraft-block/1`) in the interface: a new one, reading one pasted or
 * uploaded, saving one to disk, and the line-by-line difference between two versions' code. */
import { saveFile } from "@plantcraft/ui";
import { t } from "./i18n";
import type { BlockFileDoc, BlockFileParameter, BlockFilePort } from "./types";

export const BLOCK_FORMAT = "plantcraft-block/1";

export const STARTER_CODE = `import numpy as np
import pandas as pd


def run(inputs, params, ctx):
    """What the block computes, in one sentence."""
    x = inputs["x"]
    value = x.rolling(params.window, min_periods=1).mean()
    return {"y": value}
`;

export function newBlockFile(): BlockFileDoc {
  return {
    format: BLOCK_FORMAT,
    name: "",
    library: "custom",
    group: "",
    tags: [],
    origin: "user",
    docs: { summary: "", description: "", reading: "", assumptions: [], limitations: [], formula: "", references: [] },
    inputs: [{ port: "x", type: "series", label: "Signal", description: "The signal it reads.", unit: "" }],
    outputs: [{ port: "y", type: "series", label: "Result", description: "What it gives.", unit: "" }],
    parameters: [{ name: "window", type: "integer", title: "Window (samples)", description: "How many samples each average spans.", default: 5, minimum: 1 }],
    code: STARTER_CODE,
  };
}

export function newPort(kind: "input" | "output", taken: string[]): BlockFilePort {
  let number = 1;
  while (taken.includes(`${kind === "input" ? "in" : "out"}_${number}`)) number += 1;
  return { port: `${kind === "input" ? "in" : "out"}_${number}`, type: "series", label: "", description: "", unit: "" };
}

export function newParameter(taken: string[]): BlockFileParameter {
  let number = 1;
  while (taken.includes(`parameter_${number}`)) number += 1;
  return { name: `parameter_${number}`, type: "number", title: "", description: "", default: 0 };
}

/** A block file from pasted text: the JSON itself, or the first JSON object inside an answer
 * (an assistant often wraps it in a fenced block). */
export function parseBlockFile(text: string): BlockFileDoc {
  const trimmed = text.trim();
  const fenced = /```(?:json)?\s*([\s\S]*?)```/.exec(trimmed);
  const candidate = fenced ? fenced[1] : trimmed.slice(trimmed.indexOf("{"), trimmed.lastIndexOf("}") + 1);
  let parsed: unknown;
  try {
    parsed = JSON.parse(candidate || trimmed);
  } catch (error) {
    throw new Error(t("Not a block file: {error}", { error: error instanceof Error ? error.message : String(error) }));
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error(t("Not a block file: a block file is a JSON object."));
  const file = parsed as Partial<BlockFileDoc>;
  return {
    ...newBlockFile(),
    ...file,
    docs: { ...newBlockFile().docs, ...(file.docs ?? { summary: "" }) },
    inputs: file.inputs ?? [],
    outputs: file.outputs ?? [],
    parameters: file.parameters ?? [],
    code: file.code ?? "",
  } as BlockFileDoc;
}

/** The file's name on disk: `custom.ua_drift.v3.json`. */
export function fileName(file: BlockFileDoc): string {
  const base = file.block_id || `${file.library}.${(file.name || "block").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "")}`;
  return `${base}${file.version?.number ? `.v${file.version.number}` : ""}.json`;
}

export function downloadBlockFile(file: BlockFileDoc): void {
  saveFile(fileName(file), JSON.stringify(file, null, 2), "application/json");
}

/** Whether two files differ in their ports (a new version that changes how blocks are wired). */
export function contractChanged(before: BlockFileDoc, after: BlockFileDoc): boolean {
  const ports = (file: BlockFileDoc) => JSON.stringify([
    file.inputs.map((port) => [port.port, port.type, port.types ?? [], port.required ?? true, port.multiple ?? false]),
    file.outputs.map((port) => [port.port, port.type]),
  ]);
  return ports(before) !== ports(after);
}

/** The id a port or parameter takes from a name the assistant wrote ("Flow PV" → flow_pv). */
function portName(text: string, fallback: string): string {
  const name = text.normalize("NFKD").replace(/[^\w\s]/g, "").trim().toLowerCase().replace(/\s+/g, "_").replace(/^[^a-z]+/, "").slice(0, 60);
  return name || fallback;
}

/** "name: what it is" (and for a parameter "name = default: what it is"), as the assistant lists them. */
function splitItem(item: unknown): { name: string; value: string; text: string } {
  const raw = String(item ?? "").trim();
  const [head, ...rest] = raw.split(":");
  const [name, value = ""] = head.split("=").map((part) => part.trim());
  return { name, value, text: rest.join(":").trim() };
}

/** The block's next version as the assistant's "Help me change this block" card handed it over: the
 * new code, summary and what changed, on the current file (its ports and parameters stay). */
export function changedFromDraft(file: BlockFileDoc, draft: Record<string, unknown>): BlockFileDoc {
  const text = (key: string) => String(draft[key] ?? "").trim();
  return {
    ...file,
    code: text("code") || file.code,
    docs: { ...file.docs, summary: text("summary").slice(0, 500) || file.docs.summary },
    version: { number: file.version?.number ?? 0, name: file.version?.name ?? "", description: text("change") || file.version?.description || "" },
  };
}

/** A block file from the fields the assistant's card handed over (Link's "new-block" work): the
 * form starts filled in, and the person checks, tests and creates it there. */
export function blockFromDraft(draft: Record<string, unknown>): BlockFileDoc {
  const file = newBlockFile();
  const list = (key: string) => (Array.isArray(draft[key]) ? draft[key] as unknown[] : []);
  const ports = (key: string, kind: "in" | "out"): BlockFilePort[] => list(key).map((item, index) => {
    const { name, text } = splitItem(item);
    return { port: portName(name, `${kind}_${index + 1}`), type: "series", label: name, description: text, unit: "" };
  });
  const inputs = ports("inputs", "in");
  const outputs = ports("outputs", "out");
  const parameters: BlockFileParameter[] = list("parameters").map((item, index) => {
    const { name, value, text } = splitItem(item);
    const number = value === "" ? Number.NaN : Number(value);
    const type = Number.isFinite(number) ? (Number.isInteger(number) ? "integer" : "number") : value ? "text" : "number";
    return { name: portName(name, `parameter_${index + 1}`), type, title: name, description: text, default: Number.isFinite(number) ? number : value || 0 };
  });
  return {
    ...file,
    name: String(draft.name ?? "").slice(0, 120),
    origin: "assistant",
    docs: { ...file.docs, summary: String(draft.summary ?? "").slice(0, 500), description: String(draft.description ?? "") },
    inputs: inputs.length ? inputs : file.inputs,
    outputs: outputs.length ? outputs : file.outputs,
    parameters: draft.parameters === undefined ? file.parameters : parameters,
    code: String(draft.code ?? "").trim() ? String(draft.code) : file.code,
  };
}
