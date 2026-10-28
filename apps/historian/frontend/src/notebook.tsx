/** "Open in a notebook": PlantCraft's Notebooks write a notebook that already loads these signals
 * over this period (Python in the browser, offline). Shown only when PlantCraft says this person
 * may use them (API v1 ``/me``: ``notebooks_url``). */
import { PythonMark } from "@plantcraft/ui";
import { useEffect, useState } from "react";
import { t } from "./i18n";

let asked: Promise<string | null> | null = null;

/** Where this person opens data in a notebook, or null (asked once per page load). */
export function notebooksUrl(): Promise<string | null> {
  asked ??= fetch("/api/v1/me", { credentials: "same-origin", headers: { Accept: "application/json" } })
    .then((response) => (response.ok ? response.json() : null))
    .then((me) => (me && typeof me.notebooks_url === "string" ? me.notebooks_url : null))
    .catch(() => null);
  return asked;
}

/** The address that opens ``signals`` from ``start`` to ``end`` (ISO, or "-24h" and "now"). */
export function notebookHref(base: string, signals: string[], start: string, end: string, step?: number | null): string {
  const params = new URLSearchParams({ signals: signals.join(","), start, end, origin: "the Historian" });
  if (step) params.set("step", String(step));
  return `${base}?${params.toString()}`;
}

export function NotebookButton({ signals, start, end, step, disabled }: { signals: string[]; start: string; end: string; step?: number | null; disabled?: boolean }) {
  const [base, setBase] = useState<string | null>(null);
  useEffect(() => { void notebooksUrl().then(setBase); }, []);
  // At most 200 signals in one notebook (PlantCraft's limit).
  if (!base || disabled || !signals.length || signals.length > 200 || !start || !end) return null;
  // Notebooks work in a tab of their own (owner, 2026-10-24): the Historian stays open here.
  return <a className="button button-secondary" href={notebookHref(base, signals, start, end, step)} target="_blank" rel="noreferrer"
    title={t("A notebook that already loads these tags over this period (Python in your browser)")}><PythonMark size={16} /> {t("Open in a notebook")}</a>;
}
