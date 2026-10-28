/**
 * "Copy as prompt": puts a ready prompt about one object (a method, a model, an import format) on
 * the clipboard, for the AI assistant the plant allows. The module's API builds the prompt
 * (`plantcraft_sdk.prompts`, `GET /api/prompts/...`); this button only copies its text and never
 * calls the network itself. Without the clipboard API (plain http) it shows the text selected,
 * ready for Ctrl+C. Styles in base.css (`.pc-prompt-*`).
 */
import { Check, ChevronDown, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { t } from "./i18n.js";

/** What `GET /api/prompts/...` answers. */
export type PromptText = { title: string; text: string; omitted?: string[]; chars?: number };
export type PromptQuestion = { id: string; label: string };

export type CopyPromptProps = {
  /** Builds the prompt; `question` is the id of the preset picked (none: the module's default). */
  build: (question?: string) => Promise<PromptText>;
  /** Preset questions; with two or more the button opens a menu to pick one. */
  questions?: PromptQuestion[];
  label?: string;
  small?: boolean;
};

/** Copies `text`; false when the clipboard API is missing or refused (the caller shows it instead). */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (!navigator.clipboard?.writeText) return false;
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** The toast's line: what was copied and what was left out for length. */
export function copiedText(prompt: PromptText): string {
  const left = prompt.omitted?.length ? ` ${t("Left out for length: {parts}.", { parts: prompt.omitted.join(", ") })}` : "";
  return `${t("Prompt copied: paste it into your AI assistant.")}${left}`;
}

export function CopyPrompt({ build, questions = [], label, small = true }: CopyPromptProps) {
  const [menu, setMenu] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [shown, setShown] = useState<PromptText | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const area = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 5000);
    return () => window.clearTimeout(timer);
  }, [toast]);
  useEffect(() => {
    if (!menu) return;
    const close = (event: MouseEvent) => { if (!box.current?.contains(event.target as Node)) setMenu(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [menu]);
  useEffect(() => { area.current?.select(); }, [shown]);

  async function copy(question?: string) {
    setMenu(false);
    setBusy(true);
    try {
      const prompt = await build(question);
      if (await copyText(prompt.text)) setToast(copiedText(prompt));
      else setShown(prompt);
    } catch (error) {
      setToast(error instanceof Error ? error.message : t("The prompt could not be built."));
    } finally {
      setBusy(false);
    }
  }

  const choose = questions.length > 1;
  return (
    <div className="pc-prompt" ref={box}>
      <button type="button" className={`button button-secondary${small ? " button-small" : ""} pc-prompt-button`} disabled={busy} aria-haspopup={choose ? "menu" : undefined} aria-expanded={choose ? menu : undefined}
        title={t("Copy a prompt about this for your AI assistant. Nothing is sent: it only goes to your clipboard.")}
        onClick={() => (choose ? setMenu(!menu) : void copy(questions[0]?.id))}>
        <Sparkles size={14} />{label ?? t("Copy as prompt")}{choose && <ChevronDown size={13} />}
      </button>
      {menu && (
        <div className="pc-prompt-menu" role="menu">
          {questions.map((question) => (
            <button type="button" role="menuitem" key={question.id} className="pc-prompt-option" onClick={() => void copy(question.id)}>{question.label}</button>
          ))}
        </div>
      )}
      {toast && <div className="pc-prompt-toast" role="status"><Check size={14} />{toast}</div>}
      {shown && (
        <div className="dialog-backdrop" onClick={() => setShown(null)}>
          <div className="dialog pc-prompt-dialog" role="dialog" aria-label={shown.title} onClick={(event) => event.stopPropagation()}>
            <header><h2>{shown.title}</h2><button type="button" className="button button-small" aria-label={t("Close")} onClick={() => setShown(null)}><X size={16} /></button></header>
            <p className="muted">{t("This browser does not let the page use the clipboard. The text is selected: press Ctrl+C (Cmd+C on a Mac) and paste it into your AI assistant.")}</p>
            <textarea ref={area} className="pc-prompt-text" readOnly value={shown.text} rows={18} />
            <footer><button type="button" className="button button-primary" onClick={() => setShown(null)}>{t("Done")}</button></footer>
          </div>
        </div>
      )}
    </div>
  );
}
