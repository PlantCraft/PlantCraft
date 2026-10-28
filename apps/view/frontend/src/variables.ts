/** Dashboard variables on the page (round 7, after Grafana's): what each picker offers, the
 * values picked (the address's `var-<name>`, else the default, else the first option) and what
 * they stand for ("All" is every option). The server reads the same values (views.py). */
import { useEffect, useRef, useState } from "react";
import { ALL_VALUES, windowLabel } from "./model";
import type { Variable, VariableOption } from "./types";

/** The most values one variable stands for in a read (as the server, variables.MAX_VALUES). */
export const MAX_VALUES = 24;

/** The options of a list or an interval (no read needed); null for an asset variable. */
export function staticOptions(variable: Variable): VariableOption[] | null {
  if (variable.type === "asset") return null;
  return (variable.options ?? []).map((value) => ({ value, text: variable.type === "interval" ? windowLabel(value) : value, group: null, description: "" }));
}

/** The values picked: the wanted ones the picker offers, else the default, else the first option. */
export function pickValues(variable: Variable, options: VariableOption[], wanted: string[] | undefined): string[] {
  const offered = new Set(options.map((option) => option.value));
  let picked = (wanted ?? []).filter((value) => (value === ALL_VALUES ? Boolean(variable.include_all) : offered.has(value)));
  if (picked.includes(ALL_VALUES)) return [ALL_VALUES];
  if (!variable.multi) picked = picked.slice(0, 1);
  if (picked.length) return picked;
  const fallback = variable.default ?? "";
  if (fallback === ALL_VALUES && variable.include_all) return [ALL_VALUES];
  if (fallback && offered.has(fallback)) return [fallback];
  return options.length ? [options[0].value] : [];
}

/** What picked values stand for: "All" as every option (at most MAX_VALUES), with their names. */
export function expandValues(options: VariableOption[], picked: string[]): { values: string[]; texts: string[] } {
  const chosen = picked.includes(ALL_VALUES) ? options : picked.map((value) => options.find((option) => option.value === value) ?? { value, text: value, group: null, description: "" });
  const kept = chosen.slice(0, MAX_VALUES);
  return { values: kept.map((option) => option.value), texts: kept.map((option) => option.text) };
}

export interface Resolved {
  ready: boolean;
  options: Record<string, VariableOption[]>;
  /** As picked (`$__all` kept), for the pickers and the address. */
  picked: Record<string, string[]>;
  /** What the picks stand for, for the cards. */
  values: Record<string, string[]>;
  texts: Record<string, string[]>;
}

type Fetch = (variable: Variable, parents: string[]) => Promise<VariableOption[]>;

// Each reader of options its own number, so a page that changes reader (a draft saved) waits for
// its new options before drawing cards.
const readers = new WeakMap<Fetch, number>();
let readerCount = 0;
function readerId(fetch: Fetch | null): number {
  if (!fetch) return 0;
  if (!readers.has(fetch)) readers.set(fetch, ++readerCount);
  return readers.get(fetch)!;
}

function same(a: Record<string, string[]>, b: Record<string, string[]>): boolean {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  return [...keys].every((key) => (a[key] ?? []).join("\u0000") === (b[key] ?? []).join("\u0000"));
}

/** The variables of a dashboard resolved in order (a child under its parent's values). When the
 * address asks for values the pickers do not offer, `onFix` gets the values used instead. */
export function useVariables(variables: Variable[], fetch: Fetch | null, wanted: Record<string, string[]>, onFix: (picked: Record<string, string[]>) => void): Resolved {
  const [state, setState] = useState<Resolved & { key: string }>({ key: "", ready: false, options: {}, picked: {}, values: {}, texts: {} });
  const cache = useRef(new Map<string, Promise<VariableOption[]>>());
  const variablesKey = JSON.stringify(variables);
  const wantedKey = JSON.stringify(wanted);
  // What the options depend on: the variables and who reads them (not the values picked, so a
  // pick redraws the cards without blanking the page).
  const key = `${readerId(fetch)}|${variablesKey}`;
  useEffect(() => {
    let live = true;
    void (async () => {
      const next = { key, ready: true, options: {}, picked: {}, values: {}, texts: {} } as Resolved & { key: string };
      for (const variable of variables) {
        const parents = variable.parent ? next.values[variable.parent] ?? [] : [];
        let options = staticOptions(variable);
        if (!options) {
          const key = JSON.stringify([variable, parents]);
          if (!cache.current.has(key)) cache.current.set(key, fetch ? fetch(variable, parents).catch(() => { cache.current.delete(key); return []; }) : Promise.resolve([]));
          options = await cache.current.get(key)!;
        }
        next.options[variable.name] = options;
        next.picked[variable.name] = pickValues(variable, options, wanted[variable.name]);
        const { values, texts } = expandValues(options, next.picked[variable.name]);
        next.values[variable.name] = values;
        next.texts[variable.name] = texts;
      }
      if (!live) return;
      setState(next);
      const asked = Object.fromEntries(variables.map((variable) => [variable.name, wanted[variable.name] ?? []]));
      if (!same(asked, next.picked)) onFix(next.picked);
    })();
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, wantedKey]);
  if (!variables.length) return { ready: true, options: {}, picked: {}, values: {}, texts: {} };
  return state.key === key ? state : { ...state, ready: false };
}

/** A variable's name for people. */
export function variableLabel(variable: Variable): string {
  return variable.label || variable.name;
}

