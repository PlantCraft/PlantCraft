/** Search: passages by words and meaning, each opening its document at the page. */
import { useEffect, useState } from "react";
import { useAssistantPage } from "@plantcraft/ui";
import { api } from "./api";
import { sectionName } from "./DocumentPage";
import { t } from "./i18n";
import { Marked, searchWords, snippetOf } from "./mark";
import { navigate } from "./nav";
import type { Hit, Me } from "./types";
import { ErrorBox, Heading, Link, Loading, message } from "./ui";

const FOUND_BY: Record<string, string> = { words: "words", meaning: "meaning" };

/** Searches to start from, on the demo plant's documents. */
const EXAMPLES = [
  "Why does the recycle flow cycle?",
  "FV-1003 online valve test",
  "TIC-1209 thermocouple calibration",
  "PIC-1202 oscillation incident",
];
const RECENT_KEY = "doccraft.recent-searches";
const RECENT_MAX = 6;

/** This browser's last searches, newest first. */
export function recentSearches(): string[] {
  try {
    const saved = JSON.parse(window.localStorage.getItem(RECENT_KEY) ?? "[]");
    return Array.isArray(saved) ? saved.filter((item): item is string => typeof item === "string").slice(0, RECENT_MAX) : [];
  } catch {
    return [];
  }
}

function remember(query: string): string[] {
  const next = [query, ...recentSearches().filter((item) => item !== query)].slice(0, RECENT_MAX);
  try { window.localStorage.setItem(RECENT_KEY, JSON.stringify(next)); } catch { /* private window */ }
  return next;
}

/** A passage on its document's page, the search's words marked there too. */
export function passageLink(docId: string, passageId: number, query = ""): string {
  const search = new URLSearchParams({ passage: String(passageId), ...(query ? { q: query } : {}) });
  return `/documents/${docId}?${search}`;
}

export function SearchPage({ me }: { me: Me }) {
  const params = new URLSearchParams(window.location.search);
  const [text, setText] = useState(params.get("q") ?? "");
  const [asset, setAsset] = useState(params.get("asset") ?? "");
  const [kind, setKind] = useState(params.get("kind") ?? "");
  const [kinds, setKinds] = useState<string[]>([]);
  const [hits, setHits] = useState<Hit[] | null>(null);
  // The words of the search that found the passages shown (marked in each, and on its page).
  const [asked, setAsked] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [recent, setRecent] = useState<string[]>(recentSearches);
  useEffect(() => { api.kinds().then(setKinds).catch(() => undefined); }, []);
  const run = (query = text) => {
    if (!query.trim()) return;
    setText(query);
    setRecent(remember(query.trim()));
    setBusy(true);
    setError("");
    const search = new URLSearchParams({ q: query, ...(asset ? { asset } : {}), ...(kind ? { kind } : {}) });
    window.history.replaceState(null, "", `?${search}`);
    api.search({ query: query.trim(), asset: asset.trim() || undefined, kind: kind || undefined, limit: 12 })
      .then((answer) => { setHits(answer.passages); setAsked(query.trim()); }).catch((err) => setError(message(err))).finally(() => setBusy(false));
  };
  useEffect(() => { if (text) run(text); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useAssistantPage({ page: "doccraft:search", place: t("Documents › Search"), platformUrl: me.processcraft_url,
    facts: { query: text, asset, kind, found: hits?.length ?? 0 }, view: { results: (hits ?? []).slice(0, 8).map((hit) => `${hit.number} p.${hit.page ?? "–"}`) } });
  return <>
    <Heading title={t("Search the documents")} />
    <form className="panel search-form" onSubmit={(event) => { event.preventDefault(); run(); }}>
      <input className="search-input" aria-label={t("Question or words")} value={text} onChange={(event) => setText(event.target.value)}
        placeholder={t("Why does the recycle flow cycle? · FV-1003 · teste de válvula")} maxLength={500} autoFocus />
      <div className="search-filters">
        <label>{t("Asset")}<input value={asset} onChange={(event) => setAsset(event.target.value)} placeholder="FIC-1003" maxLength={120} /></label>
        <label>{t("Kind")}<select value={kind} onChange={(event) => setKind(event.target.value)}><option value="">{t("Any")}</option>{kinds.map((item) => <option key={item} value={item}>{t(item)}</option>)}</select></label>
        <button className="button button-primary" type="submit" disabled={busy}>{t("Search")}</button>
      </div>
      {me.embedder === "hash-384" && <p className="muted">{t("The meaning model is not installed here: the search matches words only.")}</p>}
      <SearchChips label={t("Recent")} items={recent} onPick={run} />
      <SearchChips label={t("Try")} items={EXAMPLES.filter((item) => !recent.includes(item))} onPick={run} />
    </form>
    {error && <ErrorBox text={error} />}
    {busy && <Loading />}
    {hits && !busy && (hits.length
      ? <ol className="hits">{hits.map((hit) => {
        const words = searchWords(asked);
        const to = passageLink(hit.doc_id, hit.passage_id, asked);
        return <li key={hit.passage_id} className="panel hit">
          <header>
            <Link to={to} className="strong">{hit.number || hit.title}</Link>
            <span className="muted"> {hit.number ? hit.title : ""}{hit.revision ? ` · ${t("Rev. {r}", { r: hit.revision })}` : ""}{hit.page ? ` · ${t("p. {n}", { n: hit.page })}` : ""}</span>
          </header>
          <p className="hit-section">{sectionName(hit.section)}</p>
          <p className="hit-text"><Link to={to} className="hit-snippet"><Marked text={snippetOf(hit.text, words).text} words={words} /></Link></p>
          <footer className="muted">{t(hit.kind)} · {t("found by {how}", { how: hit.found_by.map((item) => t(FOUND_BY[item] ?? item)).join(t(" and ")) })}
            {hit.assets.length > 0 && <> · {hit.assets.slice(0, 6).map((item, index) => <span key={item}>{index ? ", " : ""}<button className="link-button" type="button" onClick={() => navigate(`/assets/${encodeURIComponent(item)}`)}>{item}</button></span>)}</>}</footer>
        </li>;
      })}</ol>
      : <div className="panel empty"><p>{t("No passage of the documents you may read matches.")}</p></div>)}
  </>;
}

function SearchChips({ label, items, onPick }: { label: string; items: string[]; onPick: (query: string) => void }) {
  if (!items.length) return null;
  return <p className="search-chips"><span className="muted">{label}</span>
    {items.map((item) => <button key={item} type="button" className="chip" onClick={() => onPick(item)}>{item}</button>)}</p>;
}
