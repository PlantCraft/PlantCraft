/**
 * The Modelica text editor: CodeMirror 6 with Modelica's highlighting, omc's messages as lint
 * marks, completion of library and project class names, Ctrl+S to save.
 */
import { autocompletion, closeBrackets, closeBracketsKeymap, completionKeymap, type CompletionContext, type CompletionResult } from "@codemirror/autocomplete";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { bracketMatching, foldGutter, HighlightStyle, indentOnInput, indentUnit, StreamLanguage, syntaxHighlighting } from "@codemirror/language";
import { modelica } from "@codemirror/legacy-modes/mode/modelica";
import { lintGutter, setDiagnostics, type Diagnostic } from "@codemirror/lint";
import { highlightSelectionMatches, searchKeymap } from "@codemirror/search";
import { Compartment, EditorState } from "@codemirror/state";
import { drawSelection, EditorView, highlightActiveLine, highlightActiveLineGutter, keymap, lineNumbers } from "@codemirror/view";
import { tags } from "@lezer/highlight";
import { useEffect, useRef } from "react";
import type { Message } from "./types";

const KEYWORDS = [
  "algorithm", "and", "annotation", "block", "break", "class", "connect", "connector", "constant", "constrainedby",
  "der", "discrete", "each", "else", "elseif", "elsewhen", "encapsulated", "end", "enumeration", "equation", "expandable",
  "extends", "external", "false", "final", "flow", "for", "function", "if", "import", "impure", "in", "initial", "inner",
  "input", "loop", "model", "not", "operator", "or", "outer", "output", "package", "parameter", "partial", "protected",
  "public", "pure", "record", "redeclare", "replaceable", "return", "stream", "then", "true", "type", "when", "while", "within",
  "Real", "Integer", "Boolean", "String", "time", "experiment", "Placement", "Icon", "Diagram", "Documentation", "Line",
];

const highlight = HighlightStyle.define([
  { tag: tags.keyword, color: "var(--mc-code-keyword)", fontWeight: "600" },
  { tag: [tags.typeName, tags.className], color: "var(--mc-code-type)" },
  { tag: tags.standard(tags.name), color: "var(--mc-code-builtin)" },
  { tag: [tags.number, tags.bool, tags.atom], color: "var(--mc-code-number)" },
  { tag: tags.string, color: "var(--mc-code-string)" },
  { tag: [tags.comment, tags.lineComment, tags.blockComment], color: "var(--mc-code-comment)", fontStyle: "italic" },
  { tag: tags.operator, color: "var(--mc-code-operator)" },
]);

const theme = EditorView.theme({
  "&": { height: "100%", fontSize: "13px", backgroundColor: "var(--pc-surface)", color: "var(--pc-text)" },
  ".cm-scroller": { fontFamily: "var(--pc-font-mono)", lineHeight: "1.55" },
  ".cm-gutters": { backgroundColor: "var(--pc-surface-2)", color: "var(--pc-text-4)", borderRight: "1px solid var(--pc-border-subtle)" },
  ".cm-activeLine": { backgroundColor: "color-mix(in srgb, var(--pc-primary) 6%, transparent)" },
  ".cm-activeLineGutter": { backgroundColor: "color-mix(in srgb, var(--pc-primary) 10%, transparent)" },
  "&.cm-focused .cm-cursor": { borderLeftColor: "var(--pc-text)" },
  "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection": { backgroundColor: "color-mix(in srgb, var(--pc-primary) 22%, transparent) !important" },
  ".cm-tooltip": { backgroundColor: "var(--pc-surface)", border: "1px solid var(--pc-border)", color: "var(--pc-text)" },
  ".cm-tooltip-autocomplete ul li[aria-selected]": { backgroundColor: "var(--pc-primary-soft)", color: "var(--pc-primary-text)" },
});

/** omc's messages for this file as editor marks (lines and columns count from 1). */
export function diagnostics(text: string, messages: Message[], file: string): Diagnostic[] {
  const lines = text.split("\n");
  const offset = (line: number, column: number) => {
    const at = Math.min(Math.max(line, 1), lines.length);
    let position = 0;
    for (let index = 0; index < at - 1; index += 1) position += lines[index].length + 1;
    return position + Math.min(Math.max(column - 1, 0), lines[at - 1].length);
  };
  return messages.filter((item) => item.file === file && item.line).map((item) => {
    const from = offset(item.line!, item.column ?? 1);
    let to = offset(item.end_line ?? item.line!, item.end_column ?? (item.column ?? 1) + 1);
    if (to <= from) to = Math.min(text.length, from + 1);
    return { from, to, severity: item.level === "info" ? "info" : item.level, message: item.text };
  });
}

export interface EditorProps {
  value: string;
  file: string;
  readOnly?: boolean;
  messages?: Message[];
  /** Class names to complete (the library and the project). */
  names?: () => Promise<string[]>;
  /** A line to show (1-based); a new object each time it should move. */
  reveal?: { line: number } | null;
  onChange?: (text: string) => void;
  onSave?: () => void;
}

export function Editor({ value, file, readOnly, messages = [], names, reveal, onChange, onSave }: EditorProps) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const editable = useRef(new Compartment());
  const handlers = useRef({ onChange, onSave, names });
  handlers.current = { onChange, onSave, names };

  useEffect(() => {
    let cached: string[] | null = null;
    const complete = async (context: CompletionContext): Promise<CompletionResult | null> => {
      const word = context.matchBefore(/[A-Za-z_][A-Za-z0-9_.]*/);
      if (!word || (word.from === word.to && !context.explicit)) return null;
      if (cached === null) cached = (await handlers.current.names?.().catch(() => [])) ?? [];
      const typed = word.text;
      const dot = typed.lastIndexOf(".");
      const options = new Map<string, { label: string; type: string; detail?: string }>();
      if (dot < 0) for (const keyword of KEYWORDS) options.set(keyword, { label: keyword, type: "keyword" });
      for (const name of cached) {
        if (!name.startsWith(typed.slice(0, dot + 1))) continue;
        const rest = name.slice(dot + 1);
        const part = rest.split(".")[0];
        if (part && !options.has(part)) options.set(part, { label: part, type: rest.includes(".") ? "namespace" : "class", detail: dot < 0 ? name : undefined });
      }
      return { from: word.from + dot + 1, options: [...options.values()], validFor: /^[A-Za-z0-9_]*$/ };
    };
    const state = EditorState.create({
      doc: value,
      extensions: [
        lineNumbers(), highlightActiveLineGutter(), foldGutter(), drawSelection(), history(), indentOnInput(),
        bracketMatching(), closeBrackets(), highlightActiveLine(), highlightSelectionMatches(), lintGutter(),
        StreamLanguage.define(modelica), syntaxHighlighting(highlight), indentUnit.of("  "), EditorState.tabSize.of(2),
        autocompletion({ override: [complete] }),
        keymap.of([
          { key: "Mod-s", preventDefault: true, run: () => { handlers.current.onSave?.(); return true; } },
          ...closeBracketsKeymap, ...defaultKeymap, ...searchKeymap, ...historyKeymap, ...completionKeymap, indentWithTab,
        ]),
        editable.current.of([EditorState.readOnly.of(Boolean(readOnly)), EditorView.editable.of(!readOnly)]),
        EditorView.updateListener.of((update) => { if (update.docChanged) handlers.current.onChange?.(update.state.doc.toString()); }),
        EditorView.lineWrapping,
        theme,
      ],
    });
    view.current = new EditorView({ state, parent: host.current! });
    return () => { view.current?.destroy(); view.current = null; };
    // The editor is made once per file; later values arrive through the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file]);

  useEffect(() => {
    const current = view.current;
    if (current && current.state.doc.toString() !== value) {
      current.dispatch({ changes: { from: 0, to: current.state.doc.length, insert: value } });
    }
  }, [value]);

  useEffect(() => {
    view.current?.dispatch({ effects: editable.current.reconfigure([EditorState.readOnly.of(Boolean(readOnly)), EditorView.editable.of(!readOnly)]) });
  }, [readOnly]);

  useEffect(() => {
    const current = view.current;
    if (current) current.dispatch(setDiagnostics(current.state, diagnostics(current.state.doc.toString(), messages, file)));
  }, [messages, file, value]);

  useEffect(() => {
    const current = view.current;
    if (!current || !reveal) return;
    const line = current.state.doc.line(Math.min(Math.max(reveal.line, 1), current.state.doc.lines));
    current.dispatch({ selection: { anchor: line.from }, effects: EditorView.scrollIntoView(line.from, { y: "center" }) });
    current.focus();
  }, [reveal]);

  return <div className="mc-editor" ref={host} />;
}
