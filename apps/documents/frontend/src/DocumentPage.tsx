/** One document: what it is, the assets it is about, its revisions and its text by page. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DataTable, Dialog, confirmAction, useAssistantPage } from "@plantcraft/ui";
import { ArrowLeft, BookOpen, Download, ExternalLink, RefreshCw } from "lucide-react";
import { api } from "./api";
import { formatAgo, formatDate, t } from "./i18n";
import { StatusPill } from "./LibraryPage";
import { Marked, searchWords } from "./mark";
import { navigate } from "./nav";
import type { Doc, Folder, Me, Passage } from "./types";
import { ErrorBox, Heading, Link, Loading, message } from "./ui";

/** The section's last heading, without the document title every path starts with. */
export function sectionName(section: string): string {
  const parts = section.split(" > ");
  return parts.length > 1 ? parts.slice(1).join(" › ") : parts[0];
}

function EditDialog({ doc, folders, kinds, onClose, onSaved }: { doc: Doc; folders: Folder[]; kinds: string[]; onClose: () => void; onSaved: (doc: Doc) => void }) {
  const [fields, setFields] = useState({ number: doc.number, title: doc.title, description: doc.description ?? "", kind: doc.kind, unit: doc.unit, language: doc.language, folder_id: doc.folder_id, assistant: doc.assistant });
  const [error, setError] = useState("");
  const save = () => api.update(doc.doc_id, fields).then((saved) => { onSaved(saved); onClose(); }).catch((err) => setError(message(err)));
  return <Dialog title={t("Change the document")} onClose={onClose} onSubmit={(event) => { event.preventDefault(); void save(); }}
    footer={<><button className="button button-secondary" type="button" onClick={onClose}>{t("Cancel")}</button><button className="button button-primary" type="submit">{t("Save")}</button></>}>
    <div className="form-grid">
      <label>{t("Number")}<input value={fields.number} onChange={(event) => setFields({ ...fields, number: event.target.value })} maxLength={60} /></label>
      <label className="form-wide">{t("Title")}<input value={fields.title} onChange={(event) => setFields({ ...fields, title: event.target.value })} maxLength={200} required /></label>
      <label className="form-wide">{t("Description")}<textarea rows={3} value={fields.description} onChange={(event) => setFields({ ...fields, description: event.target.value })} maxLength={1000}
        placeholder={t("What it covers, for whom, what it replaces")} /></label>
      <label>{t("Kind")}<select value={fields.kind} onChange={(event) => setFields({ ...fields, kind: event.target.value })}>{kinds.map((kind) => <option key={kind} value={kind}>{t(kind)}</option>)}</select></label>
      <label>{t("Unit")}<input value={fields.unit} onChange={(event) => setFields({ ...fields, unit: event.target.value })} maxLength={60} /></label>
      <label>{t("Folder")}<select value={fields.folder_id} onChange={(event) => setFields({ ...fields, folder_id: event.target.value })}>
        <option value="">{t("General")}</option>
        {folders.filter((item) => item.can_edit || item.folder_id === doc.folder_id).map((item) => <option key={item.folder_id} value={item.folder_id}>{item.name}</option>)}
      </select></label>
      <label>{t("Language")}<select value={fields.language} onChange={(event) => setFields({ ...fields, language: event.target.value })}>
        <option value="">{t("Not said")}</option><option value="en">English</option><option value="pt">Português</option></select></label>
    </div>
    <label className="check"><input type="checkbox" checked={fields.assistant} onChange={(event) => setFields({ ...fields, assistant: event.target.checked })} /> {t("The assistant may read it")}</label>
    {error && <ErrorBox text={error} />}
  </Dialog>;
}

function AssetsPanel({ doc, onSaved }: { doc: Doc; onSaved: (doc: Doc) => void }) {
  const manual = doc.assets.filter((item) => item.source === "manual").map((item) => item.asset_id);
  const suggested = doc.assets.filter((item) => item.source === "suggested").sort((a, b) => b.mentions - a.mentions);
  const [adding, setAdding] = useState("");
  const [error, setError] = useState("");
  const save = (assets: string[]) => api.setAssets(doc.doc_id, assets).then(onSaved).catch((err) => setError(message(err)));
  return <section className="panel">
    <h2>{t("Assets")}</h2>
    <p className="muted">{t("The assets this document is about. The assistant ranks it first when asked about one of them.")}</p>
    <div className="chips">
      {manual.map((asset) => <span key={asset} className="chip"><Link to={`/assets/${encodeURIComponent(asset)}`}>{asset}</Link>
        {doc.can_edit && <button type="button" aria-label={t("Remove {asset}", { asset })} onClick={() => void save(manual.filter((item) => item !== asset))}>×</button>}</span>)}
      {!manual.length && <span className="muted">{t("None linked yet.")}</span>}
    </div>
    {suggested.length > 0 && <>
      <h3>{t("Found in the text")}</h3>
      <div className="chips">{suggested.map((item) => <span key={item.asset_id} className="chip chip-suggested">{item.asset_id} <small>{item.mentions}×</small>
        {doc.can_edit && <button type="button" aria-label={t("Link {asset}", { asset: item.asset_id })} onClick={() => void save([...manual, item.asset_id])}>+</button>}</span>)}
        {doc.can_edit && <button className="link-button" type="button" onClick={() => void save([...manual, ...suggested.map((item) => item.asset_id)])}>{t("Link all")}</button>}
      </div>
    </>}
    {doc.can_edit && <form className="inline-form" onSubmit={(event) => { event.preventDefault(); if (adding.trim()) void save([...manual, adding.trim()]).then(() => setAdding("")); }}>
      <input aria-label={t("Asset id")} value={adding} onChange={(event) => setAdding(event.target.value)} placeholder="FIC-1003" maxLength={120} />
      <button className="button button-secondary" type="submit">{t("Link")}</button>
    </form>}
    {error && <ErrorBox text={error} />}
  </section>;
}

function TextPanel({ doc, passageId, words }: { doc: Doc; passageId: number | null; words: string[] }) {
  const [passages, setPassages] = useState<Passage[] | null>(null);
  const [page, setPage] = useState<number | "">("");
  const marked = useRef<HTMLElement>(null);
  useEffect(() => { api.passages(doc.doc_id).then(setPassages).catch(() => setPassages([])); }, [doc.doc_id, doc.current?.status]);
  useEffect(() => { marked.current?.scrollIntoView({ block: "center" }); }, [passages]);
  const pages = useMemo(() => [...new Set((passages ?? []).map((item) => item.page_from).filter((value): value is number => !!value))], [passages]);
  if (!passages) return <Loading />;
  if (!passages.length) return <section className="panel"><h2>{t("Text")}</h2><p className="muted">{doc.current?.status === "failed" ? doc.current.error : t("The text shows here once the file is read.")}</p></section>;
  const shown = page ? passages.filter((item) => (item.page_from ?? 0) <= page && page <= (item.page_to ?? item.page_from ?? 0)) : passages;
  let lastSection = "";
  return <section className="panel reader">
    <header className="reader-head"><h2>{t("Text")}</h2>
      {pages.length > 1 && <label>{t("Page")} <select value={page} onChange={(event) => setPage(event.target.value ? Number(event.target.value) : "")}>
        <option value="">{t("All")}</option>{pages.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>}
    </header>
    {shown.map((item) => {
      const heading = item.section !== lastSection ? sectionName(item.section) : "";
      lastSection = item.section;
      const mine = item.passage_id === passageId;
      return <article key={item.passage_id} ref={mine ? marked : undefined} className={mine ? "passage passage-marked" : "passage"} id={`passage-${item.passage_id}`}>
        {heading && <h3>{heading}</h3>}
        <p>{mine ? <Marked text={item.text} words={words} /> : item.text}</p>
        <small className="muted">{item.page_from ? (item.page_to && item.page_to !== item.page_from ? t("Pages {a} to {b}", { a: item.page_from, b: item.page_to }) : t("Page {n}", { n: item.page_from })) : ""}</small>
      </article>;
    })}
  </section>;
}

/** `documents/<id>`: the document; `?passage=<id>` marks the passage a search or a citation opened. */
export function DocumentPage({ me, docId }: { me: Me; docId: string }) {
  const [doc, setDoc] = useState<Doc | null>(null);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [kinds, setKinds] = useState<string[]>([]);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState("");
  const params = new URLSearchParams(window.location.search);
  const passageId = Number(params.get("passage")) || null;
  // The words of the search or the question that opened the passage, marked in it.
  const words = useMemo(() => searchWords(params.get("q") ?? ""), [params.get("q")]); // eslint-disable-line react-hooks/exhaustive-deps
  const load = useCallback(() => Promise.all([api.document(docId), api.folders(), api.kinds()])
    .then(([found, folderList, kindList]) => { setDoc(found); setFolders(folderList); setKinds(kindList); }).catch((err) => setError(message(err))), [docId]);
  useEffect(() => { void load(); }, [load]);
  const reading = doc?.current?.status === "queued" || doc?.current?.status === "indexing";
  useEffect(() => {
    if (!reading) return;
    const timer = window.setInterval(() => void api.document(docId).then(setDoc).catch(() => undefined), 3000);
    return () => window.clearInterval(timer);
  }, [reading, docId]);
  useAssistantPage(doc && { page: "doccraft:document", subject: `doc:${doc.doc_id}`, title: [doc.number, doc.title].filter(Boolean).join(" "),
    place: t("Documents › {title}", { title: doc.number || doc.title }), platformUrl: me.processcraft_url,
    facts: { document: `doc:${doc.doc_id}`, number: doc.number, title: doc.title, kind: doc.kind, unit: doc.unit, revision: doc.current?.revision ?? "",
      pages: doc.current?.pages ?? 0, status: doc.current?.status ?? "", assistant: doc.assistant, assets: doc.assets.filter((item) => item.source === "manual").map((item) => item.asset_id).slice(0, 20) } });
  if (error) return <ErrorBox text={error} />;
  if (!doc) return <Loading />;
  const current = doc.current;
  // A PDF opens at the page of the passage the search or a citation opened.
  const passagePage = Number(params.get("page")) || undefined;
  const folder = folders.find((item) => item.folder_id === doc.folder_id);
  const remove = async () => {
    if (!(await confirmAction(t("The document, its revisions and its passages are deleted. The audit log keeps the record."), { title: t("Delete {title}?", { title: doc.title }), confirm: t("Delete"), danger: true }))) return;
    api.remove(doc.doc_id).then(() => navigate("/documents")).catch((err) => setError(message(err)));
  };
  const reindex = () => api.reindex(doc.doc_id).then(() => load()).catch((err) => setError(message(err)));
  const facts: Array<[string, string]> = [
    [t("Kind"), t(doc.kind)], [t("Unit"), doc.unit || "–"], [t("Folder"), folder?.name ?? t("General")],
    [t("Revision"), current?.revision || "–"], [t("Issued"), current?.issued ? formatDate(current.issued) : "–"],
    [t("Pages"), current?.pages ? String(current.pages) : "–"], [t("File"), current?.filename ?? "–"],
    [t("The assistant"), doc.assistant && (folder?.assistant ?? true) ? t("May read it") : t("Does not read it")],
  ];
  return <>
    <Heading title={[doc.number, doc.title].filter(Boolean).join(" · ")} actions={<>
      {current?.format === "pdf" && <a className="button button-secondary" href={api.fileUrl(doc.doc_id, { inline: true, page: passagePage })} target="_blank" rel="noopener"><ExternalLink size={16} /> {t("Open the PDF")}</a>}
      {current?.format === "docx" && current.status !== "failed" && <Link to={`/documents/${doc.doc_id}/view`} className="button button-secondary"><BookOpen size={16} /> {t("Open the document")}</Link>}
      {current && <a className="button button-secondary" href={api.fileUrl(doc.doc_id)}><Download size={16} /> {t("Download")}</a>}
      {doc.can_edit && <button className="button button-secondary" type="button" onClick={() => setEditing(true)}>{t("Change")}</button>}
    </>} />
    <section className="panel doc-facts">
      {doc.description && <p className="doc-about">{doc.description}</p>}
      <dl>{facts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      <p><StatusPill status={current?.status ?? null} /> {current?.status === "failed" && <span className="send-failed">{current.error}</span>}
        {doc.can_edit && current && current.status !== "queued" && current.status !== "indexing" && <button className="link-button" type="button" onClick={() => void reindex()}><RefreshCw size={14} /> {t("Read again")}</button>}</p>
    </section>
    <div className="document-columns">
      <TextPanel doc={doc} passageId={passageId} words={words} />
      <div>
        <AssetsPanel doc={doc} onSaved={setDoc} />
        <section className="panel">
          <h2>{t("Revisions")}</h2>
          <DataTable rows={doc.revisions} rowKey={(rev) => rev.rev_id} label={t("Revisions")} initialSort={{ key: "when", descending: true }}
            columns={[
              { key: "revision", label: t("Rev."), sort: (rev) => rev.revision, render: (rev) => <a href={api.fileUrl(doc.doc_id, { revision: rev.rev_id })}>{rev.revision || "–"}</a> },
              { key: "status", label: t("Reading"), sort: (rev) => rev.status, render: (rev) => <StatusPill status={rev.status} /> },
              { key: "when", label: t("Sent"), className: "nowrap", sort: (rev) => rev.uploaded_at, render: (rev) => <>{formatAgo(rev.uploaded_at)} <span className="muted">{rev.uploaded_by}</span></> },
            ]} />
        </section>
        {doc.can_edit && <p><button className="link-button danger" type="button" onClick={() => void remove()}>{t("Delete the document")}</button></p>}
      </div>
    </div>
    {editing && <EditDialog doc={doc} folders={folders} kinds={kinds} onClose={() => setEditing(false)} onSaved={(saved) => { setDoc({ ...doc, ...saved }); void load(); }} />}
  </>;
}

/** `documents/<id>/view`: a Word file as a page (the server builds it from the file's text, in a
 * fixed set of tags, every piece escaped), with the passages' text one click back. */
export function DocumentView({ me, docId }: { me: Me; docId: string }) {
  const [doc, setDoc] = useState<Doc | null>(null);
  const [page, setPage] = useState<{ revision: string; filename: string; html: string } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    Promise.all([api.document(docId), api.view(docId)]).then(([found, shown]) => { setDoc(found); setPage(shown); }).catch((err) => setError(message(err)));
  }, [docId]);
  useAssistantPage(doc && { page: "doccraft:document", subject: `doc:${doc.doc_id}`, title: [doc.number, doc.title].filter(Boolean).join(" "),
    place: t("Documents › {title}", { title: doc.number || doc.title }), platformUrl: me.processcraft_url,
    facts: { document: `doc:${doc.doc_id}`, number: doc.number, title: doc.title, revision: doc.current?.revision ?? "" } });
  if (error) return <ErrorBox text={error} />;
  if (!doc || !page) return <Loading />;
  return <>
    <Heading title={[doc.number, doc.title].filter(Boolean).join(" · ")} actions={<>
      <Link to={`/documents/${doc.doc_id}`} className="button button-secondary"><ArrowLeft size={16} /> {t("Back to the document")}</Link>
      <a className="button button-secondary" href={api.fileUrl(doc.doc_id)}><Download size={16} /> {t("Download")}</a>
    </>} />
    <p className="muted">{page.filename}{page.revision ? ` · ${t("Rev. {r}", { r: page.revision })}` : ""} · {t("Its text, headings and tables; pictures and the page layout are in the file itself.")}</p>
    {/* The server escapes every piece of the file's text and uses only its own tags. */}
    <article className="panel doc-page" dangerouslySetInnerHTML={{ __html: page.html }} />
  </>;
}
