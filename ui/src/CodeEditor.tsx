/**
 * The suite's Python editor (`@plantcraft/ui/codeEditor`): CodeMirror 6 with Python's
 * highlighting, the code check's problems ("Line 3: …") as marks on their lines, Ctrl+S to save,
 * read-only when asked. Styles in `@plantcraft/ui/codeEditor.css`; `tall` fills the screen's
 * height (an editor opened full screen). Moved here from Analytics so every app writes Python in
 * the same editor (Alarms first, 2026-10-27).
 */
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { python } from "@codemirror/lang-python";
import { bracketMatching, foldGutter, HighlightStyle, indentOnInput, indentUnit, syntaxHighlighting } from "@codemirror/language";
import { lintGutter, setDiagnostics, type Diagnostic } from "@codemirror/lint";
import { highlightSelectionMatches, searchKeymap } from "@codemirror/search";
import { Compartment, EditorState } from "@codemirror/state";
import { drawSelection, EditorView, highlightActiveLine, highlightActiveLineGutter, keymap, lineNumbers } from "@codemirror/view";
import { tags } from "@lezer/highlight";
import { useEffect, useRef } from "react";

const highlight = HighlightStyle.define([
  { tag: [tags.keyword, tags.controlKeyword, tags.definitionKeyword, tags.moduleKeyword, tags.operatorKeyword], color: "var(--pc-violet-text)", fontWeight: "600" },
  { tag: [tags.typeName, tags.className, tags.definition(tags.className)], color: "var(--pc-info-text)" },
  { tag: [tags.function(tags.variableName), tags.function(tags.propertyName), tags.definition(tags.function(tags.variableName))], color: "var(--pc-primary-text)" },
  { tag: [tags.number, tags.bool, tags.null, tags.atom], color: "var(--pc-attention-text)" },
  { tag: [tags.string, tags.special(tags.string)], color: "var(--pc-good-text)" },
  { tag: [tags.comment, tags.lineComment, tags.blockComment, tags.docString], color: "var(--pc-text-3)", fontStyle: "italic" },
  { tag: tags.operator, color: "var(--pc-text-2)" },
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
});

/** The code check's problems ("Line 3: importing os is not allowed.") as marks on their lines. */
export function problemMarks(text: string, problems: string[]): Diagnostic[] {
  const lines = text.split("\n");
  const found: Diagnostic[] = [];
  for (const problem of problems) {
    const match = /^Line (\d+): (.*)$/.exec(problem);
    if (!match) continue;
    const line = Math.min(Math.max(Number(match[1]), 1), lines.length);
    let from = 0;
    for (let index = 0; index < line - 1; index += 1) from += lines[index].length + 1;
    found.push({ from, to: from + lines[line - 1].length, severity: "error", message: match[2] });
  }
  return found;
}

export interface CodeEditorProps {
  value: string;
  readOnly?: boolean;
  problems?: string[];
  /** A line to show (1-based); a new object each time it should move. */
  reveal?: { line: number } | null;
  label: string;
  onChange?: (text: string) => void;
  onSave?: () => void;
  /** Fill the height it is given (a full-screen editor) instead of growing with the code. */
  tall?: boolean;
}

export function CodeEditor({ value, readOnly, problems = [], reveal, label, onChange, onSave, tall = false }: CodeEditorProps) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const editable = useRef(new Compartment());
  const handlers = useRef({ onChange, onSave });
  handlers.current = { onChange, onSave };

  useEffect(() => {
    const state = EditorState.create({
      doc: value,
      extensions: [
        lineNumbers(), highlightActiveLineGutter(), foldGutter(), drawSelection(), history(), indentOnInput(),
        bracketMatching(), highlightActiveLine(), highlightSelectionMatches(), lintGutter(),
        python(), syntaxHighlighting(highlight), indentUnit.of("    "), EditorState.tabSize.of(4),
        keymap.of([
          { key: "Mod-s", preventDefault: true, run: () => { handlers.current.onSave?.(); return true; } },
          ...defaultKeymap, ...searchKeymap, ...historyKeymap, indentWithTab,
        ]),
        editable.current.of([EditorState.readOnly.of(Boolean(readOnly)), EditorView.editable.of(!readOnly)]),
        EditorView.updateListener.of((update) => { if (update.docChanged) handlers.current.onChange?.(update.state.doc.toString()); }),
        EditorView.contentAttributes.of({ "aria-label": label }),
        theme,
      ],
    });
    view.current = new EditorView({ state, parent: host.current! });
    return () => { view.current?.destroy(); view.current = null; };
    // Made once; later values arrive through the effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const current = view.current;
    if (current && current.state.doc.toString() !== value) current.dispatch({ changes: { from: 0, to: current.state.doc.length, insert: value } });
  }, [value]);

  useEffect(() => {
    view.current?.dispatch({ effects: editable.current.reconfigure([EditorState.readOnly.of(Boolean(readOnly)), EditorView.editable.of(!readOnly)]) });
  }, [readOnly]);

  useEffect(() => {
    const current = view.current;
    if (current) current.dispatch(setDiagnostics(current.state, problemMarks(current.state.doc.toString(), problems)));
  }, [problems, value]);

  useEffect(() => {
    const current = view.current;
    if (!current || !reveal) return;
    const line = current.state.doc.line(Math.min(Math.max(reveal.line, 1), current.state.doc.lines));
    current.dispatch({ selection: { anchor: line.from }, effects: EditorView.scrollIntoView(line.from, { y: "start", yMargin: 24 }) });
  }, [reveal]);

  return <div className={`pc-code${readOnly ? " pc-code-readonly" : ""}${tall ? " pc-code-tall" : ""}`} ref={host} />;
}
