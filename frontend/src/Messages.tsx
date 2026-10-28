/** Messages: conversations between people (docs/collaboration.md). Questions for a language model go to
 * Desk's Assistant (owner, 2026-10-23), which keeps each person's chats apart. */
import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { AlertTriangle, ArrowLeft, Bot, Check, Hash, LoaderCircle, MessageSquarePlus, MessagesSquare, Search, SendHorizontal, Star, UserPlus, Users, UsersRound, X } from "lucide-react";
import { Avatar, errorText, fullWhen, Go, messageParts, plainMentions, ReadToggle, ReferencePicker, RefChip, resolveOption, sameDay, shortWhen, StarButton } from "./collab";
import { collabApi, type Contact, type ContactGroup, type Contacts, type Conversation, type ConversationMember, type Id, type Message, type RefOption } from "./collabApi";
import { locale, t } from "./i18n";
import { NoticeList, NoticePane, useNotices } from "./Notifications";
import { navigate } from "./nav";
import { displayTimeZone } from "@plantcraft/ui";
import { Modal } from "./Modal";

const LIST_POLL = 10_000;
const CHAT_POLL = 4_000;
const BUSY_POLL = 1_500;

function dayLabel(value: string) {
  const date = new Date(value);
  const now = new Date();
  const yesterday = new Date(now.getTime() - 86_400_000);
  if (sameDay(date, now)) return t("Today");
  if (sameDay(date, yesterday)) return t("Yesterday");
  return date.toLocaleDateString(locale, { weekday: "long", day: "numeric", month: "long", timeZone: displayTimeZone() });
}

/** One avatar for a direct conversation, a group icon otherwise. */
function ConversationAvatar({ conversation, me }: { conversation: Conversation; me: string }) {
  const others = conversation.members.filter((member) => member.username !== me);
  if (!conversation.is_group && others.length <= 1) { const other = others[0]; return <Avatar name={other?.display_name ?? conversation.display_title} bot={other?.kind === "specialist" || other?.kind === "system"} />; }
  return <span className="co-avatar co-avatar-md co-avatar-group" aria-hidden="true"><Users /></span>;
}

export { messageParts } from "./collab";

function MessageBody({ message }: { message: Message }) {
  const parts = useMemo(() => messageParts(message.text, message.refs), [message]);
  const shown = new Set(parts.flatMap((part) => (part.kind === "ref" ? [part.ref.ref] : [])));
  const extra = message.refs.filter((item) => !shown.has(item.ref));
  return <>
    <p className="co-text">{parts.map((part, index) => part.kind === "ref" ? <RefChip key={index} item={part.ref} label={part.text} /> : part.kind === "bold" ? <strong key={index}>{part.text}</strong> : <Fragment key={index}>{part.text}</Fragment>)}</p>
    {extra.length > 0 && <div className="co-about">{extra.map((item) => <RefChip key={item.ref} item={item} label={`${item.kind_label}: ${item.title || item.id}`} />)}</div>}
    {message.meta?.kind === "notification" && <div className="msg-notice">
      {message.meta.priority && <span className={`msg-priority msg-priority-${message.meta.priority}`}>{message.meta.priority_label ?? message.meta.priority}</span>}
      {message.meta.url && <a className="button button-secondary msg-open" href={message.meta.url}>{t("Open")}</a>}
    </div>}
  </>;
}

/** How a specialist's reply was written. */
export function writerNote(meta: Message["meta"]): string {
  const writer = meta?.writer;
  if (!writer) return "";
  if (writer === "script") return meta?.fallback ? t("Scripted answer: the language model did not answer") : t("Scripted answer, no language model");
  if (writer === "error") return t("The answer failed");
  return t("Written with {model}", { model: writer });
}

/** Textarea that grows; Enter sends, Shift+Enter breaks the line. */
function Composer({ onSend, busy, placeholder, about, setAbout, hint }: { onSend: (text: string) => Promise<boolean>; busy: boolean; placeholder: string; about: RefOption | null; setAbout: (value: RefOption | null) => void; hint: string }) {
  const [text, setText] = useState("");
  const [picking, setPicking] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { const box = area.current; if (!box) return; box.style.height = "auto"; box.style.height = `${Math.min(box.scrollHeight, 180)}px`; }, [text]);
  async function submit() { const value = text.trim(); if (!value || busy) return; if (await onSend(value)) { setText(""); area.current?.focus(); } }
  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>) { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submit(); } }
  return <div className="msg-composer">
    {picking && <ReferencePicker className="msg-picker" onClose={() => setPicking(false)} onPick={(option) => { setAbout(option); setPicking(false); area.current?.focus(); }} />}
    {about && <div className="msg-about-chip"><span>{t("About")}</span><Hash /><strong>{about.kind_label}: {about.title}</strong><button type="button" className="co-icon" onClick={() => setAbout(null)} aria-label={t("Remove the reference")}><X /></button></div>}
    <div className="msg-composer-row">
      <button type="button" className={`co-icon msg-about-button${about ? " active" : ""}`} onClick={() => setPicking(!picking)} title={t("Point at an asset or an action")} aria-label={t("Choose a reference")}><Hash /></button>
      <textarea ref={area} rows={1} value={text} placeholder={placeholder} onChange={(event) => setText(event.target.value)} onKeyDown={keyDown} aria-label={t("Message")} />
      <button type="button" className="msg-send" disabled={busy || !text.trim()} onClick={() => void submit()} aria-label={t("Send")}>{busy ? <LoaderCircle className="spin" /> : <SendHorizontal />}</button>
    </div>
    <small className="msg-hint">{hint}</small>
  </div>;
}

/** The open conversation: header, messages and composer. Marks what it shows as read. */
function ChatPane({ conversationId, me, contacts, onBack, onActivity, onRead, onMark }: { conversationId: Id; me: string; contacts: Contacts | null; onBack: () => void; onActivity: () => void; onRead: () => void; onMark: (conversation: Conversation, mark: "star" | "unread", on: boolean) => Promise<void> }) {
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const [about, setAbout] = useState<RefOption | null>(null);
  const [adding, setAdding] = useState(false);
  const lastId = useRef(0);
  const readUpTo = useRef(0);
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const callbacks = useRef({ onActivity, onRead });
  useEffect(() => { callbacks.current = { onActivity, onRead }; });

  const markRead = useCallback(async (upTo: number, unread: number) => {
    if (document.visibilityState === "hidden" || (upTo <= readUpTo.current && !unread)) return;
    readUpTo.current = Math.max(readUpTo.current, upTo);
    try { await collabApi.read(conversationId, upTo || undefined); callbacks.current.onRead(); } catch { /* read again on the next poll */ }
  }, [conversationId]);

  const load = useCallback(async () => {
    try {
      const data = await collabApi.conversation(conversationId, lastId.current || undefined);
      setConversation(data.conversation);
      if (data.messages.length) {
        lastId.current = Math.max(lastId.current, ...data.messages.map((item) => item.message_id));
        setMessages((current) => { const known = new Set(current.map((item) => item.message_id)); return [...current, ...data.messages.filter((item) => !known.has(item.message_id))]; });
        if (data.messages.some((item) => item.author !== me)) callbacks.current.onActivity();
      }
      void markRead(lastId.current, data.conversation.unread);
      setError("");
    } catch (err) { setError(errorText(err)); }
  }, [conversationId, me, markRead]);

  useEffect(() => { lastId.current = 0; readUpTo.current = 0; setMessages([]); setConversation(null); stick.current = true; void load(); }, [conversationId, load]);
  const busy = (conversation?.busy ?? []).filter((name) => name !== me);
  useEffect(() => {
    const timer = window.setTimeout(() => { if (document.visibilityState !== "hidden") void load(); else setConversation((current) => current && { ...current }); }, busy.length ? BUSY_POLL : CHAT_POLL);
    return () => window.clearTimeout(timer);
  });
  useEffect(() => { const box = scroller.current; if (box && stick.current) box.scrollTop = box.scrollHeight; }, [messages, busy.length]);

  async function send(text: string) {
    setSending(true);
    try {
      const message = await collabApi.send(conversationId, text, about?.ref ?? null);
      stick.current = true;
      setMessages((current) => current.some((item) => item.message_id === message.message_id) ? current : [...current, message]);
      lastId.current = Math.max(lastId.current, message.message_id);
      setAbout(null);
      callbacks.current.onActivity();
      window.setTimeout(() => void load(), 300);
      return true;
    } catch (err) { setError(errorText(err)); return false; } finally { setSending(false); }
  }

  async function addMembers(members: string[]) {
    const updated = await collabApi.addMembers(conversationId, members);
    setConversation(updated);
    setAdding(false);
    callbacks.current.onActivity();
  }

  if (!conversation) return <section className="msg-chat"><div className="co-center">{error ? <div className="form-error"><AlertTriangle size={15} /> {error}</div> : <LoaderCircle className="spin" />}</div></section>;
  const others = conversation.members.filter((member) => member.username !== me);
  const bots = others.filter((member) => member.kind === "specialist");
  const people = others.filter((member) => member.kind !== "specialist");
  const solo = !conversation.is_group && others.length === 1 ? others[0] : null;
  const names: Record<string, ConversationMember> = Object.fromEntries(conversation.members.map((member) => [member.username, member]));
  const nameOf = (username: string) => names[username]?.display_name ?? username;
  const soloContact = solo ? contacts?.specialists.find((item) => item.username === solo.username) : undefined;
  const subtitle: ReactNode = conversation.group_id ? <><Go to={`/groups/${encodeURIComponent(conversation.group_id)}`}>{t("Group conversation")}</Go>{` · ${t("{count} participants, who follow the group", { count: conversation.members.length })}`}</>
    : solo ? (solo.kind === "specialist" ? <><span className="co-bot-tag">{t("Specialist")}</span>{soloContact?.subject || solo.role}</> : solo.role || `@${solo.username}`)
    : t("{count} participants: {names}", { count: conversation.members.length, names: conversation.members.map((member) => member.username === me ? t("you") : member.display_name).join(", ") });
  const hint = bots.length > 0 && people.length > 0 ? t("Enter sends, Shift+Enter adds a line. In a group a specialist answers when you write @{name}.", { name: bots[0].username }) : t("Enter sends, Shift+Enter adds a line. # points the message at an asset or an action.");
  return <section className="msg-chat" aria-label={t("Conversation: {title}", { title: conversation.display_title })}>
    <header className="msg-chat-head">
      <button type="button" className="co-icon msg-back" onClick={onBack} aria-label={t("Back to conversations")}><ArrowLeft /></button>
      <ConversationAvatar conversation={conversation} me={me} />
      <div className="msg-chat-title"><strong>{conversation.display_title}</strong><small>{subtitle}</small></div>
      <span className="nt-tools">
        <StarButton starred={Boolean(conversation.starred)} onToggle={() => { const on = !conversation.starred; setConversation({ ...conversation, starred: on }); void onMark(conversation, "star", on); }} />
        {/* Unread again: back to the list, where it waits bold until it is opened. */}
        <ReadToggle unread={false} onToggle={() => { void onMark(conversation, "unread", true).then(onBack); }} />
        {contacts && !conversation.group_id && <button type="button" className="co-icon msg-add" onClick={() => setAdding(true)} title={t("Add people")} aria-label={t("Add people")}><UserPlus /></button>}
      </span>
    </header>
    <div className="msg-scroll" ref={scroller} onScroll={(event) => { const box = event.currentTarget; stick.current = box.scrollHeight - box.scrollTop - box.clientHeight < 80; }}>
      {!messages.length && <div className="msg-empty-chat">
        {solo?.kind === "specialist" ? <><Avatar name={solo.display_name} bot size="lg" /><h3>{t("Ask {name}", { name: solo.display_name })}</h3><p>{soloContact?.subject ? `${soloContact.subject}. ` : ""}{t("A specialist reads what the apps published in PlantCraft and answers here. It only reads: it never changes anything.")}</p></>
          : <><MessagesSquare /><h3>{t("No messages yet")}</h3><p>{t("Write the first one. Name an asset (FIC-101) or use the # button to link it.")}</p></>}
      </div>}
      {messages.map((message, index) => {
        const previous = messages[index - 1];
        const mine = message.author === me;
        const bot = message.author_kind === "specialist" || message.author_kind === "system";
        const newDay = !previous || !sameDay(new Date(previous.created_at), new Date(message.created_at));
        const grouped = !newDay && previous?.author === message.author && new Date(message.created_at).getTime() - new Date(previous.created_at).getTime() < 5 * 60000;
        const name = message.author_name || nameOf(message.author);
        const note = bot ? writerNote(message.meta) : "";
        return <Fragment key={message.message_id}>
          {newDay && <div className="msg-day"><span>{dayLabel(message.created_at)}</span></div>}
          <div className={`msg-row${mine ? " msg-mine" : ""}${bot ? " msg-from-bot" : ""}${grouped ? " msg-grouped" : ""}`} id={`msg-${message.message_id}`}>
            {!mine && (grouped ? <span className="msg-avatar-gap" /> : <Avatar name={name} bot={bot} size="sm" />)}
            <div className="msg-bubble">
              {!mine && !grouped && (conversation.is_group || bot) && <div className="msg-author">{name}{bot && <span className="co-bot-tag">{t("Specialist")}</span>}</div>}
              <MessageBody message={message} />
              <div className="msg-meta">{note && <span className={`msg-writer${message.meta?.writer === "error" ? " msg-writer-error" : ""}`}>{note}</span>}<time dateTime={message.created_at} title={fullWhen(message.created_at)}>{new Date(message.created_at).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", timeZone: displayTimeZone() })}</time>{mine && <Check />}</div>
            </div>
          </div>
        </Fragment>;
      })}
      {busy.map((username) => <div key={username} className="msg-row msg-from-bot msg-typing" aria-live="polite"><Avatar name={nameOf(username)} bot={names[username]?.kind === "specialist"} size="sm" /><div className="msg-bubble"><span className="msg-dots"><i /><i /><i /></span>{t("{name} is writing…", { name: nameOf(username) })}</div></div>)}
    </div>
    {error && <div className="form-error msg-error"><AlertTriangle size={15} /> {error}</div>}
    <Composer onSend={send} busy={sending} about={about} setAbout={setAbout} placeholder={t("Message {name}", { name: solo ? solo.display_name : conversation.display_title })} hint={hint} />
    {adding && contacts && <ContactsDialog mode="add" contacts={contacts} me={me} exclude={conversation.members.map((member) => member.username)} onClose={() => setAdding(false)} onSubmit={({ members }) => addMembers(members)} />}
  </section>;
}

type Prefill = { to: string | null; ref: string | null; text: string };

/** Choose people and specialists: one makes a direct conversation, several a group. Also adds people to a conversation. */
function ContactsDialog({ mode, contacts, me, exclude = [], prefill, onClose, onSubmit, onOpenGroup }: { mode: "new" | "add"; contacts: Contacts; me: string; exclude?: string[]; prefill?: { members: string[]; about: RefOption | null; text: string }; onClose: () => void; onSubmit: (choice: { members: string[]; title: string; text: string; ref: string | null }) => Promise<void>; onOpenGroup?: (groupId: string) => Promise<void> }) {
  const [q, setQ] = useState("");
  const [chosen, setChosen] = useState<string[]>(prefill?.members ?? []);
  const [title, setTitle] = useState("");
  const [text, setText] = useState(prefill?.text ?? "");
  const [about, setAbout] = useState<RefOption | null>(prefill?.about ?? null);
  const [picking, setPicking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const hidden = new Set([me, ...exclude]);
  const needle = q.trim().toLowerCase();
  const match = (item: Contact) => !hidden.has(item.username) && (!needle || `${item.username} ${item.display_name} ${item.role} ${item.subject ?? ""}`.toLowerCase().includes(needle));
  const toggle = (name: string) => setChosen(chosen.includes(name) ? chosen.filter((item) => item !== name) : [...chosen, name]);
  // Choosing a group chooses its people (owner, 2026-10-23); choosing it again leaves them out.
  const groupPeople = (group: ContactGroup) => group.members.filter((name) => !hidden.has(name));
  const groupChosen = (group: ContactGroup) => groupPeople(group).length > 0 && groupPeople(group).every((name) => chosen.includes(name));
  const toggleGroup = (group: ContactGroup) => {
    const names = groupPeople(group);
    if (groupChosen(group)) setChosen(chosen.filter((name) => !names.includes(name)));
    else { setChosen([...chosen, ...names.filter((name) => !chosen.includes(name))]); if (!title && mode === "new") setTitle(group.name); }
  };
  const groups = (contacts.groups ?? []).filter((group) => groupPeople(group).length > 0 && (!needle || `${group.name} ${group.kind_label}`.toLowerCase().includes(needle)));
  async function openGroup(group: ContactGroup) {
    if (!onOpenGroup) return;
    setBusy(true); setError("");
    try { await onOpenGroup(group.group_id); } catch (err) { setError(errorText(err)); setBusy(false); }
  }
  async function submit() {
    if (!chosen.length) return;
    setBusy(true); setError("");
    try { await onSubmit({ members: chosen, title: chosen.length > 1 ? title.trim() : "", text: text.trim(), ref: about?.ref ?? null }); } catch (err) { setError(errorText(err)); setBusy(false); }
  }
  const suggested = new Set(contacts.suggested);
  const row = (item: Contact) => <li key={item.username}><button type="button" className={`msg-contact${chosen.includes(item.username) ? " chosen" : ""}`} onClick={() => toggle(item.username)} aria-pressed={chosen.includes(item.username)}>
    <Avatar name={item.display_name} bot={item.kind === "specialist"} size="sm" />
    <span><strong>{item.display_name}{item.kind === "specialist" && <span className="co-bot-tag">{t("Specialist")}</span>}{suggested.has(item.username) && <em>{t("suggested")}</em>}</strong><small>{item.kind === "specialist" ? `@${item.username}${item.subject ? ` · ${item.subject}` : ""}` : `@${item.username}${item.role ? ` · ${item.role}` : ""}`}</small></span>
    <span className="msg-check">{chosen.includes(item.username) && <Check />}</span></button></li>;
  // Specialists answer in Desk's Assistant now (owner, 2026-10-23); Messages are between people.
  const specialists: Contact[] = [];
  const people = contacts.people.filter(match);
  const heading = mode === "add" ? t("Add people") : t("New conversation");
  return <Modal label={heading} eyebrow={<><MessagesSquare size={13} /> {t("Messages")}</>} title={heading} description={mode === "add" ? t("They will see the whole conversation.") : t("Choose a person or a specialist. Choose several, or a group of people, to make a group.")} onClose={onClose} className="msg-new">
    <div className="msg-new-body">
      <label className="co-search"><Search /><input autoFocus value={q} onChange={(event) => setQ(event.target.value)} placeholder={t("Search by name, role or subject")} aria-label={t("Search people and specialists")} /></label>
      {specialists.length > 0 && <><h4><Bot /> {t("Specialists")}</h4><ul className="msg-contacts">{specialists.map(row)}</ul></>}
      {groups.length > 0 && <><h4><UsersRound /> {t("Groups")}</h4><ul className="msg-contacts">{groups.map((group) => <li key={group.group_id} className="msg-group-row">
        <button type="button" className={`msg-contact${groupChosen(group) ? " chosen" : ""}`} onClick={() => toggleGroup(group)} aria-pressed={groupChosen(group)}>
          <span className="co-avatar co-avatar-sm msg-group-avatar"><UsersRound /></span>
          <span><strong>{group.name}</strong><small>{`${group.kind_label} · ${groupPeople(group).length === 1 ? t("1 person") : t("{count} people", { count: groupPeople(group).length })}`}</small></span>
          <span className="msg-check">{groupChosen(group) && <Check />}</span>
        </button>
        {mode === "new" && group.mine && onOpenGroup && <button type="button" className="as-link-button msg-group-open" disabled={busy} onClick={() => void openGroup(group)}>{t("Open the group's conversation")}</button>}
      </li>)}</ul></>}
      {people.length > 0 && <><h4><Users /> {t("People")}</h4><ul className="msg-contacts">{people.map(row)}</ul></>}
      {!specialists.length && !people.length && !groups.length && <p className="muted">{t("No one found.")}</p>}
      {mode === "new" && chosen.length > 1 && <label className="msg-field"><span>{t("Group name (optional)")}</span><input value={title} maxLength={120} onChange={(event) => setTitle(event.target.value)} placeholder={t("E.g. Shift A, U-200 oscillations")} /></label>}
      {mode === "new" && <div className="msg-field msg-first">
        <span>{t("First message (optional)")}</span>
        {about && <div className="msg-about-chip"><span>{t("About")}</span><Hash /><strong>{about.kind_label}: {about.title}</strong><button type="button" className="co-icon" onClick={() => setAbout(null)} aria-label={t("Remove the reference")}><X /></button></div>}
        <div className="msg-first-row">
          <button type="button" className={`co-icon msg-about-button${about ? " active" : ""}`} onClick={() => setPicking(!picking)} title={t("Point at an asset or an action")} aria-label={t("Choose a reference")}><Hash /></button>
          <textarea rows={3} value={text} onChange={(event) => setText(event.target.value)} aria-label={t("First message")} />
        </div>
        {picking && <ReferencePicker className="msg-picker-inline" onClose={() => setPicking(false)} onPick={(option) => { setAbout(option); setPicking(false); }} />}
      </div>}
      {error && <div className="form-error"><AlertTriangle size={15} /> {error}</div>}
    </div>
    <footer><button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button><button type="button" className="button button-primary" disabled={!chosen.length || busy} onClick={() => void submit()}>{busy && <LoaderCircle className="spin" size={15} />}{mode === "add" ? t("Add") : chosen.length > 1 ? t("Create group ({count})", { count: chosen.length + 1 }) : text.trim() ? t("Send") : t("Open conversation")}</button></footer>
  </Modal>;
}

function readPrefill(): Prefill | null {
  const params = new URLSearchParams(window.location.search);
  const to = params.get("to");
  const ref = params.get("ref");
  const text = params.get("text") ?? "";
  return to || ref || text ? { to, ref, text } : null;
}

/** The last message of a conversation in one line, references as their ids. */
function preview(conversation: Conversation, me: string) {
  const last = conversation.last_message;
  if (!last) return t("No messages");
  const who = last.author === me ? t("You: ") : conversation.is_group ? `${(last.author_name || last.author).split(" ")[0]}: ` : "";
  return `${who}${plainMentions(last.text).replace(/\*\*/g, "").slice(0, 90)}`;
}

/** Messages: the list of conversations beside the open one; on a phone one pane at a time. */
export function MessagesPage({ me, conversationId, onRead }: { me: string; conversationId: string | null; onRead: () => void }) {
  const [items, setItems] = useState<Conversation[] | null>(null);
  const [contacts, setContacts] = useState<Contacts | null>(null);
  const [prefill] = useState(readPrefill);
  const [creating, setCreating] = useState<{ members: string[]; about: RefOption | null; text: string } | null>(null);
  const [q, setQ] = useState("");
  const [error, setError] = useState("");

  const loadList = useCallback(async () => {
    try { const data = await collabApi.conversations(); setItems(data.items); setError(""); } catch (err) { setError(errorText(err)); }
  }, []);
  useEffect(() => {
    void loadList();
    const timer = window.setInterval(() => { if (document.visibilityState !== "hidden") void loadList(); }, LIST_POLL);
    return () => window.clearInterval(timer);
  }, [loadList]);
  useEffect(() => { collabApi.contacts(prefill?.ref).then(setContacts).catch((err) => setError(errorText(err))); }, [prefill]);

  // /messages?to=<username>&ref=<ref>&text=<text> opens the new-conversation form filled in.
  const handled = useRef(false);
  useEffect(() => {
    if (handled.current || !prefill || !contacts) return;
    handled.current = true;
    window.history.replaceState(window.history.state, "", window.location.pathname);
    const members = prefill.to ? [prefill.to] : contacts.suggested.slice(0, 1);
    void (prefill.ref ? resolveOption(prefill.ref) : Promise.resolve(null)).then((about) => setCreating({ members, about, text: prefill.text }));
  }, [contacts, prefill]);

  const open = (id: Id | null) => navigate(id === null ? "/messages" : `/messages/${encodeURIComponent(String(id))}`);
  async function start(choice: { members: string[]; title: string; text: string; ref: string | null }) {
    const data = await collabApi.startConversation({ members: choice.members, ...(choice.title ? { title: choice.title } : {}), ...(choice.text ? { text: choice.text } : {}), ...(choice.ref ? { ref: choice.ref } : {}) });
    setCreating(null);
    open(data.conversation.conversation_id);
    void loadList();
  }
  async function openGroup(groupId: string) {
    const conversation = await collabApi.groupConversation(groupId);
    setCreating(null);
    open(conversation.conversation_id);
    void loadList();
  }
  const read = useCallback(() => { onRead(); void loadList(); }, [onRead, loadList]);
  // The person's own marks (owner, 2026-10-28): a favorite, or unread again. Read again means opened:
  // the conversation's messages are marked read as when it is opened.
  const markConversation = useCallback(async (conversation: Conversation, mark: "star" | "unread", on: boolean) => {
    const id = conversation.conversation_id;
    setItems((current) => current && current.map((item) => item.conversation_id !== id ? item : mark === "star" ? { ...item, starred: on } : { ...item, marked_unread: on, unread: on ? Math.max(item.unread, 1) : 0 }));
    try {
      if (mark === "unread" && !on) await collabApi.read(id);
      else await collabApi.mark(`conversation:${id}`, mark, on);
      onRead();
    } catch (err) { setError(errorText(err)); }
    void loadList();
  }, [loadList, onRead]);
  // Two sections (owner, 2026-10-24): the chats, and the notifications read like an email inbox.
  const notices = conversationId === "notifications";
  const { feed, error: noticeError, mark, star, reload: reloadNotices } = useNotices(onRead);
  const [selected, setSelected] = useState<string | null>(null);
  const chosen = feed?.items.find((item) => item.key === selected) ?? null;

  const needle = q.trim().toLowerCase();
  // Apps' robots post notifications: they are listed under Notifications, not as chats.
  const chats = (items ?? []).filter((item) => item.members.some((member) => member.username !== me && member.kind !== "system"));
  // Favorites first, each part newest first as the server sends them.
  const filtered = chats.filter((item) => !needle || `${item.display_title} ${item.members.map((member) => `${member.username} ${member.display_name}`).join(" ")} ${item.last_message?.text ?? ""}`.toLowerCase().includes(needle))
    .sort((a, b) => Number(Boolean(b.starred)) - Number(Boolean(a.starred)));
  const unreadChats = chats.reduce((sum, item) => sum + item.unread, 0);
  const unreadNotices = feed?.counts.unread ?? 0;

  const newButton = <button type="button" className="button button-primary" onClick={() => setCreating({ members: [], about: null, text: "" })} disabled={!contacts}><MessageSquarePlus size={16} /> {t("New")}</button>;
  const tab = (to: string, label: string, count: number, on: boolean) => <Go to={to} className={on ? "on" : undefined}>
    {label}{count > 0 && <b aria-label={t("{count} unread", { count })}>{count > 99 ? "99+" : count}</b>}
  </Go>;
  const active = notices ? Boolean(chosen) : Boolean(conversationId);
  return <div className={`msg-page${active ? " msg-has-active" : ""}`} data-tour="messages">
    <aside className="msg-list" aria-label={notices ? t("Notifications") : t("Conversations")}>
      <header className="msg-list-head"><div><h1>{t("Messages")}</h1></div>{!notices && newButton}</header>
      <nav className="pc-segmented msg-sections" aria-label={t("Messages")}>
        {tab("/messages", t("Chats"), unreadChats, !notices)}
        {tab("/messages/notifications", t("Notifications"), unreadNotices, notices)}
      </nav>
      <label className="co-search msg-list-search"><Search /><input value={q} onChange={(event) => setQ(event.target.value)} placeholder={notices ? t("Search notifications") : t("Search conversations")} aria-label={notices ? t("Search notifications") : t("Search conversations")} /></label>
      {notices ? <NoticeList feed={feed} error={noticeError} query={q} selected={selected} onSelect={(item) => { setSelected(item.key); if (item.state === "unread") void mark([item.key], "read"); }} onMarkAll={() => void mark((feed?.items ?? []).filter((item) => item.state === "unread").map((item) => item.key), "read")} onMark={(item, state) => { void mark([item.key], state); if (state === "archived" && item.key === selected) setSelected(null); }} onStar={(item) => void star(item.key, !item.starred)} />
      : <>{error && <div className="form-error msg-error"><AlertTriangle size={15} /> {error}</div>}
      <ul className="msg-conversations">
        {items === null && !error && <li className="co-center"><LoaderCircle className="spin" /></li>}
        {filtered.map((item) => { const typing = item.busy.filter((name) => name !== me); const active = String(item.conversation_id) === conversationId; return <li key={item.conversation_id} className="msg-row-item">
          <Go to={`/messages/${encodeURIComponent(String(item.conversation_id))}`} className={`msg-item${active ? " active" : ""}${item.unread ? " unread" : ""}`}>
            <ConversationAvatar conversation={item} me={me} />
            <span className="msg-item-main"><span className="msg-item-top"><strong>{item.display_title}</strong>{item.has_specialist && !item.is_group && <Bot className="msg-item-bot" aria-label={t("Specialist")} />}{item.starred && <Star className="nt-starred" aria-label={t("Favorite")} />}<time>{shortWhen(item.last_message?.created_at ?? item.updated_at)}</time></span>
              <span className="msg-item-bottom"><small>{typing.length ? <em>{t("writing…")}</em> : preview(item, me)}</small>{item.unread > 0 && <b aria-label={t("{count} unread", { count: item.unread })}>{item.unread > 99 ? "99+" : item.unread}</b>}</span></span>
          </Go>
          <span className="nt-row-tools">
            <ReadToggle unread={item.unread > 0} onToggle={() => void markConversation(item, "unread", item.unread === 0)} />
            <StarButton starred={Boolean(item.starred)} onToggle={() => void markConversation(item, "star", !item.starred)} />
          </span></li>; })}
        {items !== null && !filtered.length && <li className="msg-list-empty">{q ? t("No conversation found.") : t("No conversations yet.")}</li>}
      </ul></>}
    </aside>
    {notices ? (chosen ? <NoticePane key={chosen.key} item={chosen} onBack={() => setSelected(null)} onMark={(state) => { void mark([chosen.key], state); if (state === "archived") setSelected(null); }} onStar={() => void star(chosen.key, !chosen.starred)} onActed={() => { void reloadNotices(); onRead(); }} />
      : <section className="msg-chat msg-chat-idle"><div className="co-center"><MessagesSquare /><h3>{t("Your notifications")}</h3><p>{t("Alarms, runs and changes others made to your actions. Open one to read it; check it when it is handled.")}</p></div></section>)
    : conversationId ? <ChatPane key={conversationId} conversationId={conversationId} me={me} contacts={contacts} onBack={() => open(null)} onActivity={() => void loadList()} onRead={read} onMark={markConversation} />
      : <section className="msg-chat msg-chat-idle"><div className="co-center"><MessagesSquare /><h3>{t("Your conversations")}</h3><p>{t("Talk with colleagues. Questions for the assistant go to Desk's Assistant, where each chat keeps its own subject.")}</p>{newButton}</div></section>}
    {creating && contacts && <ContactsDialog mode="new" contacts={contacts} me={me} prefill={creating} onClose={() => setCreating(null)} onSubmit={start} onOpenGroup={openGroup} />}
  </div>;
}

export default MessagesPage;
