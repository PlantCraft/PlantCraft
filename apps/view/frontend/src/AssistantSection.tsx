/** An assistant section of a report (prototype, E2): the text the language model last wrote
 * from what the apps found about the picked assets, the feedback box that turns a comment into
 * the next requirements, and the dialog that picks the assets and analyses. */
import { Dialog, errorMessage as message, renderMarkdown } from "@plantcraft/ui";
import { AlertTriangle, History, LoaderCircle, MessageSquareText, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { formatDate, t } from "./i18n";
import type { Analysis, AssetOption, AssistantData, AssistantVersion, Section, SectionData } from "./types";
import { ErrorBox } from "./ui";

/** What the section shows on the report page: the last text written, and the feedback. */
export function AssistantView({ section, read, tick, reportId, canEdit, editing }: { section: Section; read: () => Promise<SectionData>; tick: number; reportId: string; canEdit: boolean; editing: boolean }) {
  const [state, setState] = useState<{ data: AssistantData | null; error: string }>({ data: null, error: "" });
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<{ version: number; requirements: string } | null>(null);
  const [error, setError] = useState("");
  const [versions, setVersions] = useState<AssistantVersion[] | null>(null);
  useEffect(() => {
    let live = true;
    read().then((found) => { if (live) setState({ data: (found.data as AssistantData | null) ?? null, error: found.error ?? "" }); })
      .catch((err) => { if (live) setState({ data: null, error: message(err) }); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(section), tick]);
  const spec = section.assistant;
  const data = state.data;
  const written = data?.written ?? null;
  async function send() {
    setBusy(true); setError("");
    try {
      const answer = await api.assistantFeedback(reportId, section.section_id, feedback.trim(), written?.run_id ?? null);
      setDone({ version: answer.version, requirements: answer.requirements });
      setVersions(answer.versions);
      setFeedback("");
    } catch (err) { setError(message(err)); } finally { setBusy(false); }
  }
  async function history() {
    try { setVersions((await api.assistantHistory(reportId, section.section_id)).versions); } catch (err) { setError(message(err)); }
  }
  return <div className="tc-report-assistant">
    <h3><Sparkles size={15} aria-hidden /> {section.title || t("Assistant")}</h3>
    <p className="muted tc-report-assistant-scope">
      {t("Reads {analyses} about {n} picked assets", { analyses: (spec?.analyses ?? []).join(", "), n: spec?.asset_ids.length ?? 0 })}
      {data && <> · {t("now {assets} assets, {results} results, {events} events in the period", { assets: data.assets, results: data.results, events: data.events })}</>}
      {spec && <> · {t("requirements v{n}", { n: spec.version })}</>}
    </p>
    {state.error && <div className="tc-card-error" role="alert"><AlertTriangle size={15} /> {state.error}</div>}
    {!data && !state.error && <div className="tc-card-loading"><LoaderCircle className="spin" /></div>}
    {data && (written
      ? <><div className="pc-markdown">{renderMarkdown(written.text)}</div>
        <small className="muted">{t("Written {when} with requirements v{n}. The PDF keeps what was sent.", { when: formatDate(written.written_at, { dateStyle: "medium", timeStyle: "short" }), n: written.version })}</small></>
      : <p className="muted">{t("Not written yet: the model writes it when the report is made (Download PDF, Send now or the schedule).")}</p>)}
    {canEdit && !editing && written && <div className="tc-report-feedback">
      <label><MessageSquareText size={14} aria-hidden /> {t("Feedback for the next edition")}
        <textarea rows={2} maxLength={4000} value={feedback} placeholder={t("Too long; start with the loops that got worse; add the valve findings…")} onChange={(event) => setFeedback(event.target.value)} />
      </label>
      <div className="tc-report-feedback-row">
        <button type="button" className="button button-secondary" onClick={() => void history()}><History size={14} /> {t("Versions")}</button>
        <button type="button" className="button button-primary" disabled={busy || !feedback.trim()} onClick={() => void send()}>{busy ? t("Updating…") : t("Update the requirements")}</button>
      </div>
      {error && <ErrorBox text={error} />}
      {done && <div className="notice notice-ok" role="status">{t("Requirements v{n} saved: the next edition follows them.", { n: done.version })}<pre className="tc-report-requirements">{done.requirements}</pre></div>}
      {versions && <ol className="tc-report-versions">{versions.map((item) => <li key={item.version}>
        <b>v{item.version}</b> {formatDate(item.created_at, { dateStyle: "short", timeStyle: "short" })}{item.created_by ? ` · ${item.created_by}` : ""}
        {item.feedback && <blockquote>{item.feedback}</blockquote>}
        <details><summary>{t("Requirements")}</summary><pre className="tc-report-requirements">{item.requirements}</pre></details>
      </li>)}</ol>}
    </div>}
  </div>;
}

/** Which assets and analyses the assistant reads, and its requirements. */
export function AssistantDialog({ section, onSave, onClose }: { section: Section; onSave: (section: Section) => void; onClose: () => void }) {
  const spec = section.assistant ?? { asset_ids: [], children: true, analyses: ["loops"], requirements: "", version: 1 };
  const [value, setValue] = useState({ ...section, assistant: spec });
  const [assets, setAssets] = useState<AssetOption[] | null>(null);
  const [analyses, setAnalyses] = useState<Analysis[]>([]);
  const [filter, setFilter] = useState("");
  const [describe, setDescribe] = useState("");
  const [why, setWhy] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    api.assets().then(setAssets).catch((err) => { setAssets([]); setError(message(err)); });
    api.analyses().then(setAnalyses).catch(() => setAnalyses([]));
  }, []);
  const now = value.assistant;
  const set = (next: Partial<typeof now>) => setValue({ ...value, assistant: { ...now, ...next } });
  const toggle = (list: string[], item: string) => (list.includes(item) ? list.filter((x) => x !== item) : [...list, item]);
  // Units and larger first, so a whole unit is one tick; the rest by name.
  const listed = useMemo(() => {
    const rank: Record<string, number> = { site: 0, area: 1, unit: 2 };
    const needle = filter.trim().toLowerCase();
    return (assets ?? []).filter((a) => !needle || a.name.toLowerCase().includes(needle) || a.kind.includes(needle))
      .sort((a, b) => (rank[a.kind] ?? 5) - (rank[b.kind] ?? 5) || a.name.localeCompare(b.name)).slice(0, 300);
  }, [assets, filter]);
  async function propose() {
    setBusy(true); setError("");
    try {
      const found = await api.proposeScope(describe.trim());
      set({ asset_ids: found.asset_ids, analyses: found.analyses });
      setWhy(found.why + (found.dropped.length ? ` ${t("Left out (not assets): {ids}", { ids: found.dropped.join(", ") })}` : ""));
    } catch (err) { setError(message(err)); } finally { setBusy(false); }
  }
  return <Dialog title={t("Assistant section")} onClose={onClose} onSubmit={() => onSave(value)}>
    {error && <ErrorBox text={error} />}
    <div className="form-grid tc-settings">
      <label className="tc-wide">{t("Title")}<input autoFocus maxLength={120} value={value.title} onChange={(event) => setValue({ ...value, title: event.target.value })} /></label>
      <div className="tc-wide tc-field"><span>{t("Describe what to cover (optional)")}</span>
        <div className="tc-report-feedback-row">
          <input value={describe} maxLength={2000} placeholder={t("Weekly view of the U-100 flow loops and their valves")} onChange={(event) => setDescribe(event.target.value)} />
          <button type="button" className="button button-secondary" disabled={busy || !describe.trim()} onClick={() => void propose()}><Sparkles size={14} /> {busy ? t("Asking…") : t("Propose")}</button>
        </div>
        {why && <small className="muted">{why}</small>}
      </div>
      <fieldset className="tc-wide tc-field"><legend>{t("Analyses")}</legend>
        {analyses.map((item) => <label key={item.id} className="check"><input type="checkbox" checked={now.analyses.includes(item.id)} onChange={() => set({ analyses: toggle(now.analyses, item.id) })} /> {item.title}</label>)}
      </fieldset>
      <fieldset className="tc-wide tc-field"><legend>{t("Assets ({n} picked)", { n: now.asset_ids.length })}</legend>
        <input type="search" placeholder={t("Filter assets")} value={filter} onChange={(event) => setFilter(event.target.value)} />
        <label className="check"><input type="checkbox" checked={now.children} onChange={() => set({ children: !now.children })} /> {t("Include the assets under the picked ones")}</label>
        <div className="tc-report-asset-list">
          {assets === null ? <small className="muted">{t("Reading the assets…")}</small>
            : listed.map((asset) => <label key={asset.id} className="check"><input type="checkbox" checked={now.asset_ids.includes(asset.id)} onChange={() => set({ asset_ids: toggle(now.asset_ids, asset.id).slice(0, 60) })} /> {asset.name} <small className="muted">{asset.kind}</small></label>)}
        </div>
      </fieldset>
      <label className="tc-wide">{t("Requirements (the prompt)")}
        <textarea rows={7} maxLength={4000} value={now.requirements} placeholder={t("Leave empty for the default: a short summary, the assets that need attention with evidence, suggested actions.")} onChange={(event) => set({ requirements: event.target.value })} />
        <small className="muted">{t("Feedback on a written edition updates these and keeps every version.")}</small>
      </label>
    </div>
    <footer><button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button><button className="button button-primary" type="submit" disabled={!now.asset_ids.length || !now.analyses.length}>{t("Apply")}</button></footer>
  </Dialog>;
}
