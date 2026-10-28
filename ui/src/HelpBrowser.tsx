/**
 * The help of every app: guides filed in folders (their category, "A/B" nests), each folder
 * folds, a filter finds a guide by title, and the chosen guide reads on the right.
 * Works the same with 4 guides or 40.
 */
import { ChevronRight, FileText, Folder, FolderOpen, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { t } from "./i18n.js";
import { renderMarkdown } from "./Markdown.js";

export type HelpDoc = { id: string; title: string; category?: string };

type FolderNode = { name: string; path: string; folders: FolderNode[]; docs: HelpDoc[] };

/** Guides grouped into a folder tree, in the order they came. */
export function helpTree(docs: HelpDoc[]): FolderNode {
  const root: FolderNode = { name: "", path: "", folders: [], docs: [] };
  for (const doc of docs) {
    const parts = (doc.category ?? "").split("/").map((part) => part.trim()).filter(Boolean);
    let node = root;
    for (const part of parts) {
      const path = node.path ? `${node.path}/${part}` : part;
      let next = node.folders.find((folder) => folder.path === path);
      if (!next) {
        next = { name: part, path, folders: [], docs: [] };
        node.folders.push(next);
      }
      node = next;
    }
    node.docs.push(doc);
  }
  return root;
}

function folderOf(docs: HelpDoc[], id: string): string {
  return (docs.find((doc) => doc.id === id)?.category ?? "").split("/").map((part) => part.trim()).filter(Boolean).join("/");
}

function FolderView({ node, open, toggle, selected, choose, depth }: { node: FolderNode; open: (path: string) => boolean; toggle: (path: string) => void; selected: string; choose: (id: string) => void; depth: number }) {
  return (
    <ul className="pcs-help-list">
      {node.folders.map((folder) => {
        const expanded = open(folder.path);
        return (
          <li key={folder.path}>
            <button className="pcs-help-folder" aria-expanded={expanded} onClick={() => toggle(folder.path)} style={{ paddingLeft: 8 + depth * 14 }}>
              <ChevronRight size={14} className={expanded ? "pcs-turned-down" : ""} />
              {expanded ? <FolderOpen size={15} /> : <Folder size={15} />}
              <span>{folder.name}</span>
            </button>
            {expanded && <FolderView node={folder} open={open} toggle={toggle} selected={selected} choose={choose} depth={depth + 1} />}
          </li>
        );
      })}
      {node.docs.map((doc) => (
        <li key={doc.id}>
          <button className={`pcs-help-doc${doc.id === selected ? " pcs-active" : ""}`} aria-current={doc.id === selected ? "page" : undefined} onClick={() => choose(doc.id)} style={{ paddingLeft: 30 + depth * 14 }}>
            <FileText size={14} />
            <span>{doc.title}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

export type HelpBrowserProps = {
  docs: HelpDoc[];
  /** The guide's Markdown. */
  load: (id: string) => Promise<string>;
  /** Guide to open first (e.g. from ?doc=); default the first. */
  initial?: string;
  /** Told when the person opens a guide (to keep ?doc= in the address). */
  onOpen?: (id: string) => void;
  title?: string;
};

export function HelpBrowser({ docs, load, initial, onOpen, title }: HelpBrowserProps) {
  const first = docs.find((doc) => doc.id === initial)?.id ?? docs[0]?.id ?? "";
  const [selected, setSelected] = useState(first);
  const [content, setContent] = useState("");
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");
  const [opened, setOpened] = useState<Set<string>>(() => {
    const path = folderOf(docs, first);
    const parts = path ? path.split("/") : [];
    return new Set(parts.map((_, index) => parts.slice(0, index + 1).join("/")));
  });
  // Only the latest chosen guide may fill the page.
  const latest = useRef("");
  useEffect(() => {
    if (!selected) return;
    latest.current = selected;
    load(selected)
      .then((text) => {
        if (latest.current === selected) {
          setContent(text);
          setError("");
        }
      })
      .catch((err: unknown) => {
        if (latest.current === selected) setError(err instanceof Error ? err.message : t("Couldn't open the guide."));
      });
  }, [selected, load]);
  const shown = useMemo(() => {
    const words = filter.trim().toLowerCase();
    return words ? docs.filter((doc) => `${doc.title} ${doc.category ?? ""}`.toLowerCase().includes(words)) : docs;
  }, [docs, filter]);
  const tree = useMemo(() => helpTree(shown), [shown]);
  function toggle(path: string) {
    const next = new Set(opened);
    if (next.has(path)) next.delete(path);
    else next.add(path);
    setOpened(next);
  }
  function choose(id: string) {
    setSelected(id);
    onOpen?.(id);
  }
  return (
    <div className="pcs-help">
      <nav className="pcs-help-index" aria-label={title ?? t("Help")}>
        <label className="pcs-help-filter">
          <Search size={14} aria-hidden="true" />
          <input type="search" value={filter} onChange={(event) => setFilter(event.target.value)} placeholder={t("Find a guide")} aria-label={t("Find a guide")} />
        </label>
        {shown.length ? <FolderView node={tree} open={(path) => Boolean(filter.trim()) || opened.has(path)} toggle={toggle} selected={selected} choose={choose} depth={0} /> : <p className="pcs-help-empty">{t("No guide matches.")}</p>}
      </nav>
      <article className="pcs-help-document markdown-document">{error ? <p className="pcs-help-error">{error}</p> : renderMarkdown(content)}</article>
    </div>
  );
}
