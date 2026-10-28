/**
 * The library browser: the Modelica Standard Library as a tree (read lazily) and a search.
 * A class is dragged onto the diagram to add it, or opened to read its icon, parameters,
 * documentation and text. Above it, the block libraries every project shares (`/blocks`).
 */
import { ChevronDown, ChevronRight, Puzzle, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "./api";
import { t } from "./i18n";
import type { BlockLibrary, LibraryEntry } from "./types";
import { ClassBadge, Link, message } from "./ui";

/** What a dragged library class carries (the diagram's drop target reads it). */
export const CLASS_DRAG = "application/x-modelica-class";

function Node({ entry, depth, onOpen }: { entry: LibraryEntry; depth: number; onOpen: (name: string) => void }) {
  const [open, setOpen] = useState(false);
  const [children, setChildren] = useState<LibraryEntry[] | null>(null);
  const [error, setError] = useState("");
  const toggle = () => {
    setOpen(!open);
    if (!children) api.library(entry.name).then((answer) => setChildren(answer.classes)).catch((err) => setError(message(err)));
  };
  const placeable = !["package", "type", "function", "pure function", "impure function", "record"].includes(entry.restriction) && !entry.partial;
  return <li>
    <div className={`mc-tree-row${placeable ? " mc-draggable" : ""}`} style={{ paddingLeft: depth * 14 + 4 }}
      draggable={placeable} title={entry.comment || entry.name}
      onDragStart={(event) => { event.dataTransfer.setData(CLASS_DRAG, entry.name); event.dataTransfer.setData("text/plain", entry.name); event.dataTransfer.effectAllowed = "copy"; }}>
      {entry.has_children
        ? <button type="button" className="mc-twisty" onClick={toggle} aria-label={open ? t("Collapse") : t("Expand")} aria-expanded={open}>{open ? <ChevronDown /> : <ChevronRight />}</button>
        : <span className="mc-twisty" />}
      <button type="button" className="mc-tree-label" onClick={() => (entry.restriction === "package" && entry.has_children ? toggle() : onOpen(entry.name))} onDoubleClick={() => onOpen(entry.name)}>
        <ClassBadge restriction={entry.restriction} partial={entry.partial} />
        <span>{entry.short}</span>
      </button>
    </div>
    {open && (error ? <p className="mc-tree-note danger">{error}</p> : !children ? <p className="mc-tree-note muted">{t("Loading…")}</p>
      : <ul>{children.map((child) => <Node key={child.name} entry={child} depth={depth + 1} onOpen={onOpen} />)}</ul>)}
  </li>;
}

export function LibraryBrowser({ ready, onOpen }: { ready: boolean; onOpen: (name: string) => void }) {
  const [roots, setRoots] = useState<LibraryEntry[] | null>(null);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<LibraryEntry[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!ready) return;
    api.library("").then((answer) => setRoots(answer.classes)).catch((err) => setError(message(err)));
  }, [ready]);
  useEffect(() => {
    if (!ready || query.trim().length < 2) { setFound(null); return; }
    const timer = window.setTimeout(() => {
      api.library("", query.trim()).then((answer) => setFound(answer.classes)).catch((err) => setError(message(err)));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [query, ready]);
  if (!ready) return <p className="mc-tree-note muted">{t("The library is being read by the Modelica runner…")}</p>;
  return <div className="mc-library">
    <label className="mc-search">
      <Search aria-hidden="true" />
      <input type="search" value={query} placeholder={t("Search the library")} aria-label={t("Search the library")} onChange={(event) => setQuery(event.target.value)} />
    </label>
    {error && <p className="mc-tree-note danger">{error}</p>}
    {found ? <ul className="mc-tree">
      {found.length === 0 && <li className="mc-tree-note muted">{t("No class matches.")}</li>}
      {found.map((entry) => <Node key={entry.name} entry={{ ...entry, has_children: false, short: entry.name.replace(/^Modelica\./, "") }} depth={0} onOpen={onOpen} />)}
    </ul> : !roots ? <p className="mc-tree-note muted">{t("Loading…")}</p>
      : <ul className="mc-tree">{roots.map((entry) => <Node key={entry.name} entry={entry} depth={0} onOpen={onOpen} />)}</ul>}
  </div>;
}

/** The shared block libraries, by group: each block dragged into the diagram like a library class. */
export function BlocksBrowser() {
  const [libraries, setLibraries] = useState<BlockLibrary[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.blocks().then(setLibraries).catch((err) => setError(message(err))); }, []);
  if (error) return <p className="mc-tree-note danger">{error}</p>;
  if (!libraries) return null;
  const groups = new Map<string, BlockLibrary[]>();
  for (const library of libraries) groups.set(library.group || t("Other"), [...(groups.get(library.group || t("Other")) ?? []), library]);
  return <div className="mc-blocks">
    <p className="mc-tree-heading"><Puzzle aria-hidden="true" />{t("Blocks")} <Link to="/blocks" className="text-link small">{t("All")}</Link></p>
    {libraries.length === 0 ? <p className="mc-tree-note muted">{t("No block library yet.")}</p> : <ul className="mc-tree">
      {[...groups.entries()].map(([group, items]) => <li key={group}><details>
        <summary className="mc-tree-row">{group} <small className="muted">{items.reduce((sum, item) => sum + item.blocks.length, 0)}</small></summary>
        <ul>{items.flatMap((library) => library.blocks.map((block) => <li key={block.name}>
          <div className="mc-tree-row mc-draggable" style={{ paddingLeft: 18 }} draggable title={`${block.name}${block.comment ? ` · ${block.comment}` : ""}`}
            onDragStart={(event) => { event.dataTransfer.setData(CLASS_DRAG, block.name); event.dataTransfer.setData("text/plain", block.name); event.dataTransfer.effectAllowed = "copy"; }}>
            <span className="mc-tree-label"><ClassBadge restriction={block.restriction} /><span>{block.short}</span></span>
          </div>
        </li>))}</ul>
      </details></li>)}
    </ul>}
  </div>;
}
