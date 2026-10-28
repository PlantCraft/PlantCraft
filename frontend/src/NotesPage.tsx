/**
 * Desk › Notes (owner, round 7, 2026-10-24): a person's notes, in the shape of Apple Notes and
 * OneNote. Private by default; the owner shares one with people or groups, and whoever it is
 * shared with writes in it too. The editor (Tiptap) has headings, lists, a checklist and `#`
 * mentions of assets and actions; the line under the cursor becomes a to-do or an action. A
 * calendar event opens its note with `?event=event:12&title=…`. Saved as one types.
 */
import { Mention } from "@tiptap/extension-mention";
import { TaskItem, TaskList } from "@tiptap/extension-list";
import { Placeholder } from "@tiptap/extensions";
import { EditorContent, useEditor, type Editor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import type { SuggestionKeyDownProps, SuggestionProps } from "@tiptap/suggestion";
import { ArrowRightCircle, Bold, CalendarDays, Code, Heading2, Italic, List, ListChecks, ListOrdered, ListTodo, Lock, Pin, PinOff, Plus, Quote, Search, Share2, StickyNote, Trash2, Users, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useAssistantPage } from "@plantcraft/ui";
import { errorText, isLocalHref, shortWhen } from "./collab";
import { collabApi, type Contacts, type RefOption } from "./collabApi";
import { PageHeading } from "./DeskPages";
import { deskApi, type Note, type NoteSummary } from "./deskApi";
import { t } from "./i18n";
import { navigate } from "./nav";
import "./collab.css";
import "./desk.css";

const SAVE_AFTER_MS = 700;

/** `?note=4`, or `?event=event:12&title=Shift handover` (a calendar event's note). */
export function notePlace(search: string): { note: number | null; event: string | null; title: string } {
  const params = new URLSearchParams(search);
  return { note: Number(params.get("note")) || null, event: params.get("event"), title: params.get("title") ?? "" };
}

/** The `#` mentions written in one block of a note (to carry them into an action). */
export function mentionsIn(node: { type?: string; attrs?: Record<string, unknown>; content?: unknown[] } | null | undefined): string[] {
  if (!node) return [];
  const own = node.type === "mention" && typeof node.attrs?.id === "string" ? [node.attrs.id] : [];
  return [...new Set([...own, ...(node.content ?? []).flatMap((child) => mentionsIn(child as typeof node))])];
}

type Popup = { items: RefOption[]; index: number; rect: DOMRect | null; pick: (item: RefOption) => void };

/** The `#` mention: the server's references (assets and actions), picked from a small list. */
function mentionExtension(setPopup: (popup: Popup | null) => void, popupRef: { current: Popup | null }) {
  return Mention.configure({
    HTMLAttributes: { class: "co-ref dk-mention" },
    renderText: ({ node }) => `#${node.attrs.label ?? node.attrs.id}`,
    renderHTML: ({ options, node }) => ["span", { ...options.HTMLAttributes, "data-type": "mention", "data-id": node.attrs.id }, `#${node.attrs.label ?? node.attrs.id}`],
    suggestion: {
      char: "#",
      items: async ({ query }) => { try { return await collabApi.references(query); } catch { return []; } },
      render: () => {
        const show = (props: SuggestionProps<RefOption>) => setPopup({
          items: props.items, index: 0, rect: props.clientRect?.() ?? null,
          pick: (item) => props.command({ id: item.ref, label: item.title }),
        });
        return {
          onStart: show,
          onUpdate: show,
          onKeyDown: ({ event }: SuggestionKeyDownProps) => {
            const popup = popupRef.current;
            if (!popup || !popup.items.length) return false;
            if (event.key === "Escape") { setPopup(null); return true; }
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              const step = event.key === "ArrowDown" ? 1 : -1;
              setPopup({ ...popup, index: (popup.index + step + popup.items.length) % popup.items.length });
              return true;
            }
            if (event.key === "Enter" || event.key === "Tab") { popup.pick(popup.items[popup.index]); return true; }
            return false;
          },
          onExit: () => setPopup(null),
        };
      },
    },
  });
}

function Tool({ label, on, onClick, children }: { label: string; on?: boolean; onClick: () => void; children: ReactNode }) {
  return <button type="button" className={`pcs-icon-button${on ? " on" : ""}`} aria-label={label} title={label} aria-pressed={on} onMouseDown={(event) => event.preventDefault()} onClick={onClick}>{children}</button>;
}

function Toolbar({ editor, onTodo, onAction }: { editor: Editor; onTodo: () => void; onAction: () => void }) {
  const chain = () => editor.chain().focus();
  return <div className="dk-note-toolbar" role="toolbar" aria-label={t("Format")}>
    <Tool label={t("Bold")} on={editor.isActive("bold")} onClick={() => chain().toggleBold().run()}><Bold size={15} /></Tool>
    <Tool label={t("Italic")} on={editor.isActive("italic")} onClick={() => chain().toggleItalic().run()}><Italic size={15} /></Tool>
    <Tool label={t("Heading")} on={editor.isActive("heading", { level: 2 })} onClick={() => chain().toggleHeading({ level: 2 }).run()}><Heading2 size={15} /></Tool>
    <Tool label={t("Bulleted list")} on={editor.isActive("bulletList")} onClick={() => chain().toggleBulletList().run()}><List size={15} /></Tool>
    <Tool label={t("Numbered list")} on={editor.isActive("orderedList")} onClick={() => chain().toggleOrderedList().run()}><ListOrdered size={15} /></Tool>
    <Tool label={t("Checklist")} on={editor.isActive("taskList")} onClick={() => chain().toggleTaskList().run()}><ListChecks size={15} /></Tool>
    <Tool label={t("Quote")} on={editor.isActive("blockquote")} onClick={() => chain().toggleBlockquote().run()}><Quote size={15} /></Tool>
    <Tool label={t("Code")} on={editor.isActive("codeBlock")} onClick={() => chain().toggleCodeBlock().run()}><Code size={15} /></Tool>
    <span className="dk-note-toolbar-gap" />
    <button type="button" className="button button-secondary button-small" onMouseDown={(event) => event.preventDefault()} onClick={onTodo} title={t("The line under the cursor becomes a to-do.")}><ListTodo size={14} /> {t("Line to to-do")}</button>
    <button type="button" className="button button-secondary button-small" onMouseDown={(event) => event.preventDefault()} onClick={onAction} title={t("The line under the cursor becomes an action, with its # mentions.")}><ArrowRightCircle size={14} /> {t("Line to action")}</button>
  </div>;
}

function Sharing({ note, contacts, onChange }: { note: Note; contacts: Contacts | null; onChange: (shared: string[]) => void }) {
  const taken = new Set(note.shared.map((item) => item.ref));
  const people = (contacts?.people ?? []).filter((person) => person.kind === "person" && person.username !== note.owner && !taken.has(`user:${person.username}`));
  const groups = (contacts?.groups ?? []).filter((group) => !taken.has(`group:${group.group_id}`));
  return <div className="dk-note-share" aria-label={t("Shared with")}>
    {note.shared.length === 0 && <span className="muted small"><Lock size={13} aria-hidden="true" /> {t("Only you")}</span>}
    {note.shared.map((item) => <span key={item.ref} className="dk-chip on">
      {item.ref.startsWith("group:") ? <Users size={12} aria-hidden="true" /> : null}{item.name}
      {note.mine && <button type="button" className="pcs-icon-button" aria-label={t("Stop sharing with {name}", { name: item.name })} onClick={() => onChange(note.shared.map((entry) => entry.ref).filter((ref) => ref !== item.ref))}><X size={12} /></button>}
    </span>)}
    {note.mine && (people.length > 0 || groups.length > 0) && <select id="dk-note-share" value="" aria-label={t("Share with")} onChange={(event) => { if (event.target.value) onChange([...taken, event.target.value]); }}>
      <option value="">{t("Share with…")}</option>
      {people.length > 0 && <optgroup label={t("People")}>{people.map((person) => <option key={person.username} value={`user:${person.username}`}>{person.display_name}</option>)}</optgroup>}
      {groups.length > 0 && <optgroup label={t("Groups")}>{groups.map((group) => <option key={group.group_id} value={`group:${group.group_id}`}>{group.name}</option>)}</optgroup>}
    </select>}
  </div>;
}

function NoteEditor({ note, contacts, onSaved, onGone }: { note: Note; contacts: Contacts | null; onSaved: (note: Note) => void; onGone: () => void }) {
  const [title, setTitle] = useState(note.title);
  const [current, setCurrent] = useState(note);
  const [state, setState] = useState<"saved" | "saving" | "error">("saved");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState<{ text: string; href: string } | null>(null);
  const [popup, setPopupState] = useState<Popup | null>(null);
  const popupRef = useRef<Popup | null>(null);
  const setPopup = useCallback((value: Popup | null) => { popupRef.current = value; setPopupState(value); }, []);
  const timer = useRef<number | null>(null);
  const pending = useRef<Parameters<typeof deskApi.changeNote>[1]>({});

  const flush = useCallback(async () => {
    if (timer.current) { window.clearTimeout(timer.current); timer.current = null; }
    const change = pending.current;
    if (!Object.keys(change).length) return;
    pending.current = {};
    setState("saving");
    try { const saved = await deskApi.changeNote(note.note_id, change); setCurrent(saved); onSaved(saved); setState("saved"); setError(""); } catch (err) { setState("error"); setError(errorText(err)); }
  }, [note.note_id, onSaved]);
  const later = useCallback((change: Parameters<typeof deskApi.changeNote>[1]) => {
    pending.current = { ...pending.current, ...change };
    setState("saving");
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => void flush(), SAVE_AFTER_MS);
  }, [flush]);
  useEffect(() => () => { void flush(); }, [flush]);

  const extensions = useMemo(() => [
    StarterKit.configure({ heading: { levels: [2, 3] }, link: { openOnClick: false } }),
    TaskList, TaskItem.configure({ nested: true }),
    Placeholder.configure({ placeholder: t("Write here. # mentions an asset or an action.") }),
    mentionExtension(setPopup, popupRef),
  ], [setPopup]);
  const editor = useEditor({
    extensions,
    content: Object.keys(note.body ?? {}).length ? note.body : "",
    editorProps: { attributes: { class: "dk-note-body", "aria-label": t("Note"), role: "textbox", "aria-multiline": "true" } },
    onUpdate: ({ editor: changed }) => later({ body: changed.getJSON(), text: changed.getText({ blockSeparator: "\n" }) }),
  }, [note.note_id]);

  function line(): { text: string; refs: string[] } | null {
    if (!editor) return null;
    const { $from } = editor.state.selection;
    const block = $from.parent;
    const text = block.textContent.trim();
    return text ? { text: text.slice(0, 200), refs: mentionsIn(block.toJSON()) } : null;
  }
  async function toTodo() {
    const picked = line();
    if (!picked) { setError(t("Put the cursor on a line with text first.")); return; }
    try {
      const made = await deskApi.createTodo({ title: picked.text, notes: t("From the note {title}.", { title: title || t("Untitled") }) });
      setError("");
      setNotice({ text: t("To-do added: {title}", { title: made.title }), href: `/todo?view=all&item=${made.todo_id}` });
    } catch (err) { setError(errorText(err)); }
  }
  async function toAction() {
    const picked = line();
    if (!picked) { setError(t("Put the cursor on a line with text first.")); return; }
    try {
      const made = await collabApi.createAction({ title: picked.text, description: t("From the note {title}.", { title: title || t("Untitled") }), priority: "medium", owner: null, due_at: null, refs: picked.refs });
      setError("");
      setNotice({ text: t("Action created: {title}", { title: made.title }), href: `/actions/${made.action_id}` });
    } catch (err) { setError(errorText(err)); }
  }
  async function owner(change: Parameters<typeof deskApi.changeNote>[1]) {
    try { const saved = await deskApi.changeNote(note.note_id, change); setCurrent(saved); onSaved(saved); setError(""); } catch (err) { setError(errorText(err)); }
  }
  async function remove() {
    if (!window.confirm(t("Delete the note {title}?", { title: title || t("Untitled") }))) return;
    pending.current = {};
    try { await deskApi.deleteNote(note.note_id); onGone(); } catch (err) { setError(errorText(err)); }
  }
  function follow(target: EventTarget) {
    const mention = (target as HTMLElement).closest?.("[data-type='mention']");
    const ref = mention?.getAttribute("data-id");
    const href = ref ? current.refs.find((item) => item.ref === ref)?.href : null;
    if (href && isLocalHref(href)) navigate(href);
  }

  return <section className="panel dk-note-editor" aria-label={title || t("Untitled")}>
    <header className="dk-note-head">
      <input id="dk-note-title" className="dk-note-title" value={title} maxLength={200} placeholder={t("Title")} aria-label={t("Title")}
        onChange={(event) => { setTitle(event.target.value); later({ title: event.target.value }); }} />
      <span className="dk-note-state muted small" role="status">{state === "saving" ? t("Saving…") : state === "error" ? t("Not saved") : t("Saved")}</span>
      {current.mine && <button type="button" className="pcs-icon-button" aria-label={current.pinned ? t("Unpin") : t("Pin")} title={current.pinned ? t("Unpin") : t("Pin")} aria-pressed={current.pinned} onClick={() => void owner({ pinned: !current.pinned })}>{current.pinned ? <PinOff size={15} /> : <Pin size={15} />}</button>}
      {current.mine && <button type="button" className="pcs-icon-button danger" aria-label={t("Delete")} title={t("Delete")} onClick={() => void remove()}><Trash2 size={15} /></button>}
    </header>
    <div className="dk-note-meta">
      <Share2 size={13} aria-hidden="true" className="muted" />
      <Sharing note={current} contacts={contacts} onChange={(shared) => void owner({ shared })} />
      {!current.mine && <span className="muted small">{t("Owned by {name}", { name: current.owner_name })}</span>}
      {current.event_ref && <a className="dk-chip" href="/calendar" onClick={(event) => { event.preventDefault(); navigate("/calendar"); }}><CalendarDays size={12} aria-hidden="true" /> {t("Calendar event")}</a>}
    </div>
    {editor && <Toolbar editor={editor} onTodo={() => void toTodo()} onAction={() => void toAction()} />}
    {error && <p className="form-error small">{error}</p>}
    {notice && <p className="dk-note-notice small" role="status">{notice.text} <a href={notice.href} onClick={(event) => { event.preventDefault(); navigate(notice.href); }}>{t("Open")}</a></p>}
    <div className="dk-note-page" onClick={(event) => follow(event.target)}>
      <EditorContent editor={editor} />
    </div>
    {popup && popup.rect && <div className="co-picker dk-note-mentions" role="listbox" aria-label={t("References")} style={{ position: "fixed", left: popup.rect.left, top: popup.rect.bottom + 4 }}>
      <div className="co-picker-list">{popup.items.length
        ? popup.items.map((item, index) => <button type="button" role="option" aria-selected={index === popup.index} className={index === popup.index ? "on" : undefined} key={item.ref} onMouseDown={(event) => { event.preventDefault(); popup.pick(item); }}>
          <span className="co-kind">{item.kind_label}</span><strong>{item.title}</strong><small>{item.detail || item.ref}</small>
        </button>)
        : <div className="co-picker-empty">{t("Nothing found.")}</div>}</div>
    </div>}
  </section>;
}

export function NotesPage() {
  const first = useMemo(() => notePlace(window.location.search), []);
  const [items, setItems] = useState<NoteSummary[] | null>(null);
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<number | null>(first.note);
  const [note, setNote] = useState<Note | null>(null);
  const [contacts, setContacts] = useState<Contacts | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    deskApi.notes(q).then((value) => { setItems(value.items); setError(""); }).catch((err) => setError(errorText(err)));
  }, [q]);
  useEffect(() => { const timer = window.setTimeout(load, q ? 200 : 0); return () => window.clearTimeout(timer); }, [load, q]);
  useEffect(() => { collabApi.contacts().then(setContacts).catch(() => setContacts(null)); }, []);
  // The notes are private: the assistant gets the open note's start and the titles listed, nothing else.
  useAssistantPage({
    place: t("Desk › Notes"), page: "processcraft:notes",
    facts: { notes: items?.length ?? 0 },
    view: { search: q, open: note ? { title: note.title.slice(0, 120), start: note.body_text.slice(0, 300) } : null, listed: (items ?? []).slice(0, 30).map((item) => item.title.slice(0, 80)) },
  });
  useEffect(() => {
    if (!first.event) return;
    deskApi.notes("", first.event).then(async (found) => {
      const made = found.items[0] ?? await deskApi.createNote({ title: first.title, event_ref: first.event });
      setSelected(made.note_id);
      load();
    }).catch((err) => setError(errorText(err)));
  }, [first, load]);
  useEffect(() => {
    if (!selected) { setNote(null); return; }
    deskApi.note(selected).then(setNote).catch((err) => { setError(errorText(err)); setSelected(null); });
  }, [selected]);
  useEffect(() => {
    window.history.replaceState(window.history.state, "", `/notes${selected ? `?note=${selected}` : ""}`);
  }, [selected]);
  async function create() {
    try { const made = await deskApi.createNote({ title: "" }); setSelected(made.note_id); load(); } catch (err) { setError(errorText(err)); }
  }
  const saved = useCallback((value: Note) => {
    setItems((list) => list?.map((item) => (item.note_id === value.note_id ? { ...item, ...value, body_text: value.body_text.slice(0, 160) } : item)) ?? list);
  }, []);
  const pinned = (items ?? []).filter((item) => item.pinned);
  const rest = (items ?? []).filter((item) => !item.pinned);
  const row = (item: NoteSummary) => <li key={item.note_id}>
    <button type="button" className={`dk-note-row${item.note_id === selected ? " on" : ""}`} aria-current={item.note_id === selected ? "true" : undefined} onClick={() => setSelected(item.note_id)}>
      <strong>{item.title || t("Untitled")}</strong>
      <small className="muted">{shortWhen(item.updated_at)}{item.body_text ? ` · ${item.body_text}` : ""}</small>
      <span className="dk-note-row-tags">
        {item.pinned && <Pin size={12} aria-label={t("Pinned")} />}
        {item.shared.length > 0 && <Users size={12} aria-label={t("Shared")} />}
        {item.event_ref && <CalendarDays size={12} aria-label={t("Calendar event")} />}
        {!item.mine && <span>{item.owner_name}</span>}
      </span>
    </button>
  </li>;
  return <>
    <PageHeading eyebrow={t("Desk")} title={t("Notes")} description={t("Your notes: private until you share them with people or groups. # mentions an asset or an action; a line becomes a to-do or an action.")}
      action={<button type="button" className="button button-primary" onClick={() => void create()}><Plus size={15} /> {t("New note")}</button>} />
    {error && <div className="form-error">{error}</div>}
    <div className="dk-notes">
      <nav className="panel dk-notes-list" aria-label={t("Notes")}>
        <label className="dk-notes-search"><Search size={14} aria-hidden="true" /><input id="dk-notes-search" type="search" value={q} onChange={(event) => setQ(event.target.value)} placeholder={t("Search notes")} aria-label={t("Search notes")} /></label>
        {!items && !error && <p className="muted small">{t("Loading…")}</p>}
        {items && !items.length && <p className="muted small dk-todo-empty">{q ? t("No note has that.") : t("No notes yet.")}</p>}
        {pinned.length > 0 && <><h3>{t("Pinned")}</h3><ul>{pinned.map(row)}</ul></>}
        {rest.length > 0 && <>{pinned.length > 0 && <h3>{t("Notes")}</h3>}<ul>{rest.map(row)}</ul></>}
      </nav>
      {note
        ? <NoteEditor key={note.note_id} note={note} contacts={contacts} onSaved={saved} onGone={() => { setSelected(null); load(); }} />
        : <section className="panel dk-note-empty"><StickyNote size={28} aria-hidden="true" /><p className="muted">{t("Pick a note, or start a new one.")}</p></section>}
    </div>
  </>;
}
