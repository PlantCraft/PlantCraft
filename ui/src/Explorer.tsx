/**
 * Explorer: one way to find any value or event of the suite (Alarms round 11). A person goes
 * into the plant as into folders, asset by asset; each asset shows everything the suite has
 * about it, whatever app wrote it: its signals by role, the series the apps computed about it
 * (Link's health, an algorithm's outputs), the events that named it (open conditions first) and
 * its children. Or types a few words ("FIC-1001 health") and lands on the value.
 *
 * The app answers through its own routes (API v1 `GET /api/v1/explore`, read with the person's
 * token, `plantcraft_sdk.explore`): `load(assetId?)` and `search(words)`; `preview` shows the
 * last value of what is chosen. `onPick` hands back what the person chose, with `relativeTo`
 * (the asset it was found on) so an editor can offer "this asset" for rules over many assets.
 */
import { ChevronRight, Folder, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { t } from "./i18n.js";

export interface ExploreStep { id: string; name: string }
export interface ExploreChild { id: string; name: string; kind?: string | null; children: number; roles: number }
export interface ExploreSignal { role: string; id: string; name: string; unit: string; kind?: string }
export interface ExploreOutput { id: string; name: string; unit: string; app: string; app_name: string; result?: string; kind?: string }
export interface ExploreEvent { kind: string; app: string; title: string; count: number; last_at: string; open: number; severity: string }
export interface ExploreAnswer {
  asset: { id: string; name: string; kind?: string | null; type_path?: string[] } | null;
  path: ExploreStep[];
  children: ExploreChild[];
  signals?: ExploreSignal[];
  outputs?: ExploreOutput[];
  events?: ExploreEvent[];
}
export interface ExploreHit {
  type: "asset" | "signal" | "output";
  id: string; name: string; unit?: string; kind?: string | null; role?: string; app?: string; app_name?: string;
  path: ExploreStep[];
}
/** What a person picked: a value (a plant signal or an app's series), an event kind, or an asset. */
export interface ExplorePick {
  type: "signal" | "output" | "event" | "asset";
  id: string;
  name: string;
  unit?: string;
  role?: string;
  app?: string;
  /** The asset it was found on (its path's last step), for "this asset" in a rule over many. */
  relativeTo?: string | null;
  path: ExploreStep[];
}
export type ExploreWant = "value" | "event" | "asset";

/** The pick a search hit stands for. */
export function pickOfHit(hit: ExploreHit): ExplorePick {
  const owner = hit.type === "asset" ? null : hit.path[hit.path.length - 1]?.id ?? null;
  return { type: hit.type, id: hit.id, name: hit.name, unit: hit.unit, role: hit.role, app: hit.app, relativeTo: owner, path: hit.path };
}

/** Whether a kind of pick is one the caller wants. */
export function wanted(want: ExploreWant[], type: ExplorePick["type"]): boolean {
  if (type === "event") return want.includes("event");
  if (type === "asset") return want.includes("asset");
  return want.includes("value");
}

/** "Unit 100 › FIC-1001" (the steps' names). */
export function pathWords(path: ExploreStep[]): string {
  return path.map((step) => step.name).join(" › ");
}

/** The outputs grouped by the app that computed them, apps in order of first appearance. */
export function outputsByApp(outputs: ExploreOutput[]): Array<{ app: string; name: string; outputs: ExploreOutput[] }> {
  const groups: Array<{ app: string; name: string; outputs: ExploreOutput[] }> = [];
  for (const output of outputs) {
    let group = groups.find((item) => item.app === output.app);
    if (!group) groups.push(group = { app: output.app, name: output.app_name || output.app, outputs: [] });
    group.outputs.push(output);
  }
  return groups;
}

export interface ExplorerProps {
  load: (assetId?: string) => Promise<ExploreAnswer>;
  search: (words: string) => Promise<{ hits: ExploreHit[] }>;
  onPick: (pick: ExplorePick) => void;
  /** What may be picked (default: values). */
  want?: ExploreWant[];
  /** The last value of a signal or series, shown before the person picks it. */
  preview?: (signalId: string) => Promise<{ value: unknown; at?: string | null; unit?: string | null }>;
  /** The asset to open first. */
  start?: string;
  label?: string;
}

export function Explorer({ load, search, onPick, want = ["value"], preview, start, label }: ExplorerProps) {
  const [at, setAt] = useState<string | undefined>(start);
  const [answer, setAnswer] = useState<ExploreAnswer | null>(null);
  const [words, setWords] = useState("");
  const [hits, setHits] = useState<ExploreHit[] | null>(null);
  const [chosen, setChosen] = useState<ExplorePick | null>(null);
  const [shown, setShown] = useState<string>("");
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    load(at).then((found) => { if (live) { setAnswer(found); setError(""); } }).catch((err) => { if (live) setError(String(err?.message ?? err)); });
    return () => { live = false; };
  }, [at, load]);

  useEffect(() => {
    const text = words.trim();
    if (!text) { setHits(null); return; }
    let live = true;
    const timer = window.setTimeout(() => {
      search(text).then((found) => { if (live) setHits(found.hits); }).catch(() => { if (live) setHits([]); });
    }, 200);
    return () => { live = false; window.clearTimeout(timer); };
  }, [words, search]);

  useEffect(() => {
    setShown("");
    if (!chosen || !preview || (chosen.type !== "signal" && chosen.type !== "output")) return;
    let live = true;
    preview(chosen.id).then((found) => {
      if (!live) return;
      const value = typeof found.value === "number" ? found.value.toLocaleString(undefined, { maximumFractionDigits: 3 }) : String(found.value ?? "–");
      setShown(t("Last value: {value} {unit}", { value, unit: found.unit ?? chosen.unit ?? "" }).trim());
    }).catch(() => { if (live) setShown(t("No value yet.")); });
    return () => { live = false; };
  }, [chosen, preview]);

  const here = answer?.asset?.id ?? null;
  const choose = (pick: ExplorePick) => setChosen(pick);
  const item = (pick: ExplorePick, detail: string, key: string) => {
    const allowed = wanted(want, pick.type);
    const on = chosen?.type === pick.type && chosen.id === pick.id && chosen.relativeTo === pick.relativeTo;
    return <li key={key}><button type="button" className={`pc-explore-item${on ? " on" : ""}`} disabled={!allowed} onClick={() => choose(pick)} onDoubleClick={() => allowed && onPick(pick)}>
      <span>{pick.name}</span><small>{detail}</small>
    </button></li>;
  };

  return <div className="pc-explorer" aria-label={label ?? t("Explorer")}>
    <div className="pc-explore-search">
      <Search size={15} aria-hidden="true" />
      <input type="search" value={words} onChange={(event) => setWords(event.target.value)} placeholder={t("Search the plant: FIC-1001 health")} aria-label={t("Search the plant")} />
    </div>
    {error && <p className="pc-explore-error">{error}</p>}
    {hits ? <ul className="pc-explore-list" aria-label={t("Results")}>
      {hits.length === 0 && <li className="pc-explore-empty">{t("Nothing matches every word.")}</li>}
      {hits.map((hit) => hit.type === "asset"
        ? <li key={`a:${hit.id}`}><button type="button" className="pc-explore-item" onClick={() => { setWords(""); setAt(hit.id); }}>
          <span><Folder size={14} aria-hidden="true" /> {hit.name}</span><small>{pathWords(hit.path) || t("Plant")}</small></button></li>
        : item(pickOfHit(hit), `${pathWords(hit.path)}${hit.type === "output" ? ` · ${hit.app_name ?? hit.app}` : hit.role ? ` · ${hit.role}` : ""}`, `${hit.type}:${hit.id}`))}
    </ul> : <>
      <nav className="pc-explore-path" aria-label={t("Where you are")}>
        <button type="button" onClick={() => setAt(undefined)}>{t("Plant")}</button>
        {answer?.path.map((step) => <span key={step.id}><ChevronRight size={13} aria-hidden="true" /><button type="button" onClick={() => setAt(step.id)} aria-current={step.id === here ? "location" : undefined}>{step.name}</button></span>)}
      </nav>
      {answer && <div className="pc-explore-body">
        {answer.children.length > 0 && <section><h4>{here ? t("Inside") : t("The plant")}</h4><ul className="pc-explore-list">
          {answer.children.map((child) => <li key={child.id}><button type="button" className="pc-explore-item" onClick={() => setAt(child.id)}>
            <span><Folder size={14} aria-hidden="true" /> {child.name}</span>
            <small>{[child.kind, child.children ? t("{count} inside", { count: child.children }) : "", child.roles ? t("{count} signals", { count: child.roles }) : ""].filter(Boolean).join(" · ")}</small>
          </button></li>)}
        </ul></section>}
        {here && (answer.signals?.length ?? 0) > 0 && <section><h4>{t("Signals")}</h4><ul className="pc-explore-list">
          {answer.signals!.map((signal) => item({ type: "signal", id: signal.id, name: signal.role, unit: signal.unit, role: signal.role, relativeTo: here, path: answer.path }, `${signal.name}${signal.unit ? ` · ${signal.unit}` : ""}`, `s:${signal.role}`))}
        </ul></section>}
        {here && outputsByApp(answer.outputs ?? []).map((group) => <section key={group.app}><h4>{t("Computed by {app}", { app: group.name })}</h4><ul className="pc-explore-list">
          {group.outputs.map((output) => item({ type: "output", id: output.id, name: output.name, unit: output.unit, app: output.app, relativeTo: here, path: answer.path }, `${output.unit ? `${output.unit} · ` : ""}${output.id}`, `o:${output.id}`))}
        </ul></section>)}
        {here && want.includes("event") && <section><h4>{t("Events about it (30 days)")}</h4>
          {(answer.events?.length ?? 0) === 0 ? <p className="pc-explore-empty">{t("No app reported anything about this asset.")}</p> : <ul className="pc-explore-list">
            {answer.events!.map((event) => item({ type: "event", id: event.kind, name: event.title, app: event.app, relativeTo: here, path: answer.path },
              [event.open ? t("{count} open now", { count: event.open }) : "", t("{count} in 30 days", { count: event.count }), event.kind].filter(Boolean).join(" · "), `e:${event.kind}`))}
          </ul>}
        </section>}
        {here && want.includes("asset") && <p><button type="button" className="button button-small button-secondary" onClick={() => onPick({ type: "asset", id: here, name: answer.asset!.name, path: answer.path })}>{t("Use {name}", { name: answer.asset!.name })}</button></p>}
      </div>}
    </>}
    {chosen && <div className="pc-explore-chosen">
      <div><b>{chosen.name}</b><small>{[pathWords(chosen.path), shown].filter(Boolean).join(" · ")}</small></div>
      <button type="button" className="button button-small button-primary" onClick={() => onPick(chosen)}>{t("Use it")}</button>
    </div>}
  </div>;
}
