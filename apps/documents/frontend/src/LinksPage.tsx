import { useEffect, useState } from "react";
import { api } from "./api";
import { t } from "./i18n";
import type { LinkToCheck } from "./types";
import { ErrorBox, Heading, Link, Loading, message } from "./ui";

const key = (link: LinkToCheck) => `${link.doc_id}|${link.asset_id}`;

/** D5: the assets found in the documents' text that wait for a person, approved or rejected
 * several at once. Above the installation's threshold a link is taken at once and is not here. */
export function LinksPage() {
  const [data, setData] = useState<{ threshold: number; links: LinkToCheck[] } | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () => api.linksToCheck().then((next) => { setData(next); setPicked(new Set()); }).catch((err) => setError(message(err)));
  useEffect(() => { void load(); }, []);
  if (!data) return error ? <ErrorBox text={error} /> : <Loading />;
  const toggle = (k: string) => setPicked((old) => { const next = new Set(old); if (next.has(k)) next.delete(k); else next.add(k); return next; });
  const review = (verdict: "approved" | "rejected") => {
    const links = data.links.filter((link) => picked.has(key(link))).map((link) => ({ doc_id: link.doc_id, asset_id: link.asset_id }));
    setBusy(true);
    api.reviewLinks(links, verdict).then(load).catch((err) => setError(message(err))).finally(() => setBusy(false));
  };
  const all = data.links.length > 0 && picked.size === data.links.length;
  return <>
    <Heading title={t("Links to check")} actions={<>
      <button type="button" className="button button-primary" disabled={!picked.size || busy} onClick={() => review("approved")}>{t("Correct ({n})", { n: picked.size })}</button>
      <button type="button" className="button button-secondary" disabled={!picked.size || busy} onClick={() => review("rejected")}>{t("Wrong ({n})", { n: picked.size })}</button>
    </>} />
    <p className="muted">{data.threshold > 0
      ? t("Assets named at least {n} times in a document are linked at once. These were named fewer times: mark each Correct to link it or Wrong to stop suggesting it.", { n: data.threshold })
      : t("The assets named in each document's text. Mark each Correct to link it or Wrong to stop suggesting it.")}</p>
    {error && <ErrorBox text={error} />}
    {data.links.length === 0 ? <div className="panel empty">{t("Nothing to check.")}</div>
      : <div className="panel"><table className="table">
        <thead><tr>
          <th><input type="checkbox" aria-label={t("Pick all")} checked={all} onChange={() => setPicked(all ? new Set() : new Set(data.links.map(key)))} /></th>
          <th>{t("Document")}</th><th>{t("Asset")}</th><th>{t("Times named")}</th>
        </tr></thead>
        <tbody>{data.links.map((link) => <tr key={key(link)}>
          <td><input type="checkbox" aria-label={t("Pick {asset} on {doc}", { asset: link.asset_id, doc: link.number || link.title })} checked={picked.has(key(link))} onChange={() => toggle(key(link))} /></td>
          <td><Link to={`/documents/${link.doc_id}`}>{link.number || link.title}</Link> <span className="muted">{link.number ? link.title : ""}</span></td>
          <td>{link.asset_id}</td>
          <td>{link.mentions}</td>
        </tr>)}</tbody>
      </table></div>}
  </>;
}
