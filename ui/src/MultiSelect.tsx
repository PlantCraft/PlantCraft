/**
 * A filter that picks several values from a short list: a button that names what is chosen
 * ("Status: Alarm, Attention", or "All") and opens a list of checkboxes, each with its count.
 * The suite's lists filter with it (owner, 2026-10-21: dropdowns, not rows of buttons).
 */
import { Check, ChevronDown } from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { t } from "./i18n.js";

export type MultiSelectOption = { id: string; label: string; count?: number | null; icon?: ReactNode };

export type MultiSelectProps = {
  /** What is filtered: "Kind", "Status". */
  label: string;
  options: MultiSelectOption[];
  value: string[];
  onChange: (value: string[]) => void;
  /** The text when nothing is chosen (everything shows). */
  allLabel?: string;
};

/** The button's text: "All", the labels chosen (up to two), or "3 of 5". */
export function multiSelectSummary(options: MultiSelectOption[], value: string[], allLabel = t("All")): string {
  const chosen = options.filter((item) => value.includes(item.id));
  if (!chosen.length || chosen.length === options.length) return allLabel;
  if (chosen.length <= 2) return chosen.map((item) => item.label).join(", ");
  return t("{count} of {total}", { count: chosen.length, total: options.length });
}

export function MultiSelect({ label, options, value, onChange, allLabel }: MultiSelectProps) {
  const [open, setOpen] = useState(false);
  // Near the right edge of the window the list opens leftwards, so it is never cut off.
  const [toLeft, setToLeft] = useState(false);
  const root = useRef<HTMLDivElement | null>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    const outside = (event: MouseEvent) => { if (root.current && !root.current.contains(event.target as Node)) setOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", outside);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("mousedown", outside); document.removeEventListener("keydown", escape); };
  }, [open]);
  const toggle = (key: string) => onChange(value.includes(key) ? value.filter((item) => item !== key) : [...value, key]);
  const active = value.length > 0 && value.length < options.length;
  return (
    <div className={`pc-multi${active ? " pc-multi-active" : ""}`} ref={root}>
      <button type="button" className="pc-multi-button" aria-haspopup="listbox" aria-expanded={open} aria-controls={id} onClick={() => { const box = root.current?.getBoundingClientRect(); setToLeft(Boolean(box && box.left + 240 > window.innerWidth)); setOpen(!open); }}>
        <span className="pc-multi-label">{label}</span>
        <span className="pc-multi-value">{multiSelectSummary(options, value, allLabel)}</span>
        <ChevronDown size={14} aria-hidden="true" />
      </button>
      {open && (
        <div className={`pc-multi-pop${toLeft ? " pc-multi-pop-left" : ""}`} id={id} role="listbox" aria-multiselectable="true" aria-label={label}>
          {options.map((item) => {
            const on = value.includes(item.id);
            return (
              <button type="button" role="option" aria-selected={on} key={item.id} className={`pc-multi-option${on ? " on" : ""}`} onClick={() => toggle(item.id)}>
                <span className="pc-multi-check" aria-hidden="true">{on && <Check size={12} />}</span>
                {item.icon}
                <span className="pc-multi-text">{item.label}</span>
                {item.count !== undefined && item.count !== null && <span className="pc-multi-count">{item.count}</span>}
              </button>
            );
          })}
          {value.length > 0 && <button type="button" className="pc-multi-clear" onClick={() => onChange([])}>{t("Show all")}</button>}
        </div>
      )}
    </div>
  );
}
