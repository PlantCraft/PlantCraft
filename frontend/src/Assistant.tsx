/**
 * Desk's Assistant: each person's own chats with a language model, apart
 * from Messages (which stay between people). Many chats at once, each on its own subject, all
 * about the plant and the platform: it declines anything else. The model reads the plant only through
 * read-only tools, as the person who asks; each answer shows what it read (steps), the charts it
 * drew from the plant's history and the objects it used.
 *
 * The history ("like ChatGPT's"): groups of the person's own, archived chats
 * apart, and a chat shared like a dashboard with people, groups or everyone, who read it and
 * continue in a copy of their own. Its reference (`chat:<id>`) goes in an action or a message.
 */
import { AlertTriangle, Archive, ArchiveRestore, Bot, Check, ChevronRight, Copy, CopyPlus, FolderInput, Hash, Link2, LoaderCircle, Mail, MailOpen, MessageSquarePlus, MoreHorizontal, Pencil, RotateCcw, SendHorizontal, Share2, Sparkles, Trash2, X } from "lucide-react";
import { AnswerProgress, AssistantChart, Dialog, formatAgo, ProposalCard, renderMarkdown } from "@plantcraft/ui";
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { errorText, Go, StarButton } from "./collab";
import { assistantApi, chatMention, chatSections, mergeMessages, settledUpTo, type AssistantStatus, type Chat, type ChatMessage, type ChatRef } from "./assistantApi";
import { collabApi, type Contacts } from "./collabApi";
import { t } from "./i18n";
import { navigate } from "./nav";
import { canSee, useAccess, useIsAdmin } from "./session";
import "./access.css";
import "./assistant.css";

/** While an answer is written: often enough to follow its text as it comes. */
const POLL_MS = 700;
const GROUP_LABELS: Record<string, string> = { starred: "Favorites", today: "Today", week: "Last 7 days", older: "Older" };
/** First questions the empty page offers: the plant and the platform. */
const STARTERS = [
  "Which loops need attention today?",
  "Plot the main signals of a unit over the last 24 hours.",
  "Which alarms were raised most often this week?",
  "How do I create a dashboard?",
];

/** What an app sent with the address (``assistantUrl`` of @plantcraft/ui): the object the chat is
 * about (?ref=asset:FIC-101), the question written in (?q=) and the app's own questions (?s=). */
function fromAddress(): { ref: string; question: string; starters: string[] } {
  const params = new URLSearchParams(window.location.search);
  return { ref: params.get("ref") ?? "", question: params.get("q") ?? "", starters: params.getAll("s").slice(0, 6) };
}

function Composer({ busy, onSend, placeholder, autoFocus, initial = "" }: { busy: boolean; onSend: (text: string) => Promise<boolean>; placeholder: string; autoFocus?: boolean; initial?: string }) {
  const [text, setText] = useState(initial);
  const area = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { setText(initial); if (initial) area.current?.focus(); }, [initial]);
  useEffect(() => {
    const box = area.current;
    if (!box) return;
    box.style.height = "auto";
    box.style.height = `${Math.min(box.scrollHeight, 220)}px`;
  }, [text]);
  async function submit() {
    const clean = text.trim();
    if (!clean || busy) return;
    if (await onSend(clean)) setText("");
  }
  function keys(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submit(); }
  }
  return <div className="asst-composer">
    <textarea ref={area} rows={1} value={text} autoFocus={autoFocus} onChange={(event) => setText(event.target.value)} onKeyDown={keys} placeholder={placeholder} aria-label={t("Your question")} maxLength={8000} />
    <button type="button" className="asst-send" disabled={busy || !text.trim()} onClick={() => void submit()} aria-label={t("Send")}>{busy ? <LoaderCircle className="spin" /> : <SendHorizontal />}</button>
  </div>;
}

function RefChip({ item }: { item: ChatRef }) {
  const label = `${item.kind_label ? `${t(item.kind_label)}: ` : ""}${item.title || item.id || item.ref}`;
  return item.href ? <Go to={item.href} className="asst-ref"><Hash size={12} />{label}</Go> : <span className="asst-ref asst-ref-plain"><Hash size={12} />{label}</span>;
}

function Steps({ message }: { message: ChatMessage }) {
  const working = message.state === "working";
  const [open, setOpen] = useState(working);
  // Open while the model reads; folded once the answer is written (one click away).
  useEffect(() => setOpen(working), [working]);
  if (!message.steps.length) return null;
  const errors = message.steps.filter((step) => step.state === "error").length;
  const label = working ? t("Reading the plant…") : t("{count} reads of the plant", { count: message.steps.length }) + (errors ? ` · ${t("{count} failed", { count: errors })}` : "");
  return <div className={`asst-steps${open ? " open" : ""}`}>
    <button type="button" className="asst-steps-head" onClick={() => setOpen((value) => !value)} aria-expanded={open}><ChevronRight size={14} />{label}</button>
    {open && <ol>{message.steps.map((step, index) => <li key={index} className={`asst-step asst-step-${step.state}`}>
      {step.state === "running" ? <LoaderCircle className="spin" size={13} /> : step.state === "error" ? <AlertTriangle size={13} /> : <Check size={13} />}
      <span><b>{t(step.title)}</b>{step.summary && <small>{step.summary}</small>}{step.error && <small className="asst-step-error">{step.error}</small>}</span>
    </li>)}</ol>}
  </div>;
}

function AnswerBody({ message, onRetry }: { message: ChatMessage; onRetry?: () => void }) {
  const [copied, setCopied] = useState(false);
  const working = message.state === "working";
  const failed = message.state === "failed";
  async function copy() {
    try { await navigator.clipboard.writeText(message.text); setCopied(true); window.setTimeout(() => setCopied(false), 1500); } catch { /* the browser refused */ }
  }
  return <>
    <Steps message={message} />
    {failed
      ? <div className="asst-failed"><AlertTriangle size={15} /> <span>{message.text || t("The answer was interrupted. Ask again.")}</span>
        {onRetry && <button type="button" className="button button-secondary asst-retry" onClick={onRetry}><RotateCcw size={14} />{t("Try again")}</button>}</div>
      : message.text && <div className={`asst-markdown${working ? " pc-answer-writing" : ""}`}>{renderMarkdown(message.text, { plainExternalLinks: true })}</div>}
    <AnswerProgress message={message} />
    {message.charts.map((chart, index) => <AssistantChart key={index} chart={chart} />)}
    {message.state === "done" && (message.meta?.proposals ?? []).map((proposal, index) => <ProposalCard key={index} chatId={message.chat_id} messageId={message.message_id} index={index} proposal={proposal} />)}
    {!working && message.refs.length > 0 && <div className="asst-refs"><span className="asst-refs-label">{t("Sources")}</span>{message.refs.map((item) => <RefChip key={item.ref} item={item} />)}</div>}
    {message.state === "done" && <div className="asst-foot">
      {message.meta?.model && <small>{message.meta.model}</small>}
      <button type="button" className="asst-tool" onClick={() => void copy()} title={t("Copy the answer")} aria-label={t("Copy the answer")}>{copied ? <Check size={14} /> : <Copy size={14} />}</button>
    </div>}
  </>;
}

async function copyText(text: string): Promise<boolean> {
  try { await navigator.clipboard.writeText(text); return true; } catch { return false; }
}

/** Who reads the chat besides its owner: no one, everyone in the workspace, or some people and groups. */
function ShareDialog({ chat, onClose, onShared }: { chat: Chat; onClose: () => void; onShared: (chat: Chat) => void }) {
  const [contacts, setContacts] = useState<Contacts | null>(null);
  const [grants, setGrants] = useState<string[]>(chat.shared ?? []);
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const isAdmin = useIsAdmin();
  useEffect(() => { collabApi.contacts().then(setContacts).catch((err) => setError(errorText(err))); }, []);
  const everyone = grants.includes("everyone");
  const toggle = (grant: string) => setGrants((current) => (current.includes(grant) ? current.filter((item) => item !== grant) : [...current, grant]));
  const match = (text: string) => text.toLowerCase().includes(filter.trim().toLowerCase());
  const people = (contacts?.people ?? []).filter((item) => item.kind === "person" && (match(item.display_name) || match(item.username)));
  const groups = (contacts?.groups ?? []).filter((item) => match(item.name));
  async function save() {
    setBusy(true); setError("");
    try { onShared(await assistantApi.share(chat.chat_id, everyone ? ["everyone"] : grants)); onClose(); } catch (err) { setError(errorText(err)); setBusy(false); }
  }
  return <Dialog title={t("Share \"{title}\"", { title: chat.title })} onClose={onClose} onSubmit={() => void save()}
    footer={<><button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button><button type="submit" className="button button-primary" disabled={busy}>{busy && <LoaderCircle className="spin" />}{t("Save")}</button></>}>
    <p className="muted small">{t("They read the chat as it is, answers and charts included, and may continue it in a copy of their own. Only you write in it.")}</p>
    <div className="ac-notice ac-notice-warn"><AlertTriangle size={15} /> {t("The assistant answered with your access: whoever reads this chat reads what it found for you, documents and app results included, even where they have no access of their own.")}</div>
    {error && <div className="form-error"><AlertTriangle size={15} /> {error}</div>}
    {(isAdmin || everyone) && <label className="asst-share-row"><input type="checkbox" checked={everyone} disabled={!isAdmin} onChange={() => setGrants(everyone ? [] : ["everyone"])} /> <strong>{t("Everyone in the workspace")}</strong>{!isAdmin && <small className="muted"> {t("Only an administrator shares with everyone.")}</small>}</label>}
    {!everyone && <>
      <input className="asst-share-filter" value={filter} onChange={(event) => setFilter(event.target.value)} placeholder={t("Find a person or a group")} aria-label={t("Find a person or a group")} />
      {!contacts ? <LoaderCircle className="spin" /> : <div className="asst-share-list">
        {groups.map((group) => <label key={group.group_id} className="asst-share-row"><input type="checkbox" checked={grants.includes(`group:${group.group_id}`)} onChange={() => toggle(`group:${group.group_id}`)} /> {group.name} <small className="muted">{group.kind_label}</small></label>)}
        {people.map((person) => <label key={person.username} className="asst-share-row"><input type="checkbox" checked={grants.includes(`user:${person.username}`)} onChange={() => toggle(`user:${person.username}`)} /> {person.display_name} <small className="muted">{person.role}</small></label>)}
      </div>}
    </>}
  </Dialog>;
}

/** What the person does with one of their chats: rename, group, archive, share, copy its link or reference, delete. */
function ChatMenu({ chat, folders, onChanged, onRename, onDelete }: { chat: Chat; folders: string[]; onChanged: () => void; onRename?: () => void; onDelete: () => void }) {
  const [open, setOpen] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [note, setNote] = useState("");
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => { if (box.current && !box.current.contains(event.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);
  async function act(run: () => Promise<unknown>) {
    setOpen(false);
    try { await run(); onChanged(); } catch (err) { setNote(errorText(err)); }
  }
  async function move() {
    const answer = window.prompt(folders.length ? t("Group (one of: {groups}; empty takes it out)", { groups: folders.join(", ") }) : t("Group name (empty takes it out)"), chat.folder ?? "");
    if (answer === null) return;
    await act(() => assistantApi.change(chat.chat_id, { folder: answer.trim() }));
  }
  async function copied(text: string, done: string) {
    setOpen(false);
    setNote((await copyText(text)) ? done : t("The browser did not let me copy it."));
    window.setTimeout(() => setNote(""), 2000);
  }
  const link = `${window.location.origin}/assistant/${chat.chat_id}`;
  return <div className="asst-menu" ref={box}>
    <button type="button" className="asst-tool" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((value) => !value)} title={t("More")} aria-label={t("More about \"{title}\"", { title: chat.title })}><MoreHorizontal size={15} /></button>
    {open && <ul role="menu" className="asst-menu-list">
      {onRename && <li><button type="button" role="menuitem" onClick={() => { setOpen(false); onRename(); }}><Pencil size={14} />{t("Rename")}</button></li>}
      <li><button type="button" role="menuitem" onClick={() => void move()}><FolderInput size={14} />{chat.folder ? t("Move to another group") : t("Put in a group")}</button></li>
      <li><button type="button" role="menuitem" onClick={() => { setOpen(false); setSharing(true); }}><Share2 size={14} />{chat.shared?.length ? t("Shared · change") : t("Share")}</button></li>
      <li><button type="button" role="menuitem" onClick={() => void copied(link, t("Link copied"))}><Link2 size={14} />{t("Copy link")}</button></li>
      <li><button type="button" role="menuitem" onClick={() => void copied(chatMention(chat), t("Reference copied: paste it in an action or a message"))}><Hash size={14} />{t("Copy reference for an action or message")}</button></li>
      <li><button type="button" role="menuitem" onClick={() => void act(() => collabApi.mark(`chat:${chat.chat_id}`, "unread", !chat.unread))}>{chat.unread ? <MailOpen size={14} /> : <Mail size={14} />}{chat.unread ? t("Mark as read") : t("Mark as unread")}</button></li>
      <li><button type="button" role="menuitem" onClick={() => void act(() => assistantApi.change(chat.chat_id, { archived: !chat.archived }))}>{chat.archived ? <ArchiveRestore size={14} /> : <Archive size={14} />}{chat.archived ? t("Bring back from the archive") : t("Archive")}</button></li>
      <li><button type="button" role="menuitem" className="asst-menu-danger" onClick={() => { setOpen(false); onDelete(); }}><Trash2 size={14} />{t("Delete")}</button></li>
    </ul>}
    {note && <span className="asst-menu-note" role="status">{note}</span>}
    {sharing && <ShareDialog chat={chat} onClose={() => setSharing(false)} onShared={() => onChanged()} />}
  </div>;
}

function ChatPane({ chatId, onChanged }: { chatId: number; onChanged: () => void }) {
  const [chat, setChat] = useState<Chat | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const working = messages.some((item) => item.state === "working");
  const load = useCallback((after: number) => assistantApi.chat(chatId, after).then((view) => {
    setChat(view.chat);
    setMessages((current) => (after ? mergeMessages(current, view.messages) : view.messages));
    setError("");
    return view;
  }), [chatId]);
  useEffect(() => { setMessages([]); setChat(null); stick.current = true; load(0).catch((err) => setError(errorText(err))); }, [load]);
  useEffect(() => {
    if (!working) return;
    const timer = window.setTimeout(() => {
      load(settledUpTo(messages)).then((view) => { if (!view.working) onChanged(); }).catch((err) => setError(errorText(err)));
    }, POLL_MS);
    return () => window.clearTimeout(timer);
  }, [working, messages, load, onChanged]);
  useEffect(() => {
    const box = scroller.current;
    if (box && stick.current) box.scrollTop = box.scrollHeight;
  }, [messages]);
  async function send(text: string) {
    setBusy(true);
    try {
      const answer = await assistantApi.ask(chatId, text);
      stick.current = true;
      setMessages((current) => mergeMessages(current, answer.messages));
      setError("");
      onChanged();
      return true;
    } catch (err) { setError(errorText(err)); return false; } finally { setBusy(false); }
  }
  async function retry() {
    setBusy(true);
    try {
      const answer = await assistantApi.retry(chatId);
      stick.current = true;
      setMessages((current) => mergeMessages(current.filter((item) => item.state !== "failed"), answer.messages));
      setError("");
    } catch (err) { setError(errorText(err)); } finally { setBusy(false); }
  }
  async function continueCopy() {
    setBusy(true);
    try { const made = await assistantApi.copy(chatId); onChanged(); navigate(`/assistant/${made.chat_id}`); } catch (err) { setError(errorText(err)); } finally { setBusy(false); }
  }
  async function rename() {
    if (editing === null || !editing.trim()) { setEditing(null); return; }
    try { setChat(await assistantApi.rename(chatId, editing.trim())); onChanged(); } catch (err) { setError(errorText(err)); }
    setEditing(null);
  }
  if (!chat) return <section className="asst-chat"><div className="asst-center">{error ? <div className="form-error"><AlertTriangle size={15} /> {error}</div> : <LoaderCircle className="spin" />}</div></section>;
  return <section className="asst-chat" aria-label={t("Chat: {title}", { title: chat.title })}>
    <header className="asst-chat-head">
      <button type="button" className="co-icon asst-back" onClick={() => navigate("/assistant")} aria-label={t("Back to chats")}><X /></button>
      <span className="asst-avatar"><Bot /></span>
      <div className="asst-chat-title">
        {editing !== null
          ? <input autoFocus value={editing} maxLength={120} onChange={(event) => setEditing(event.target.value)} onBlur={() => void rename()} onKeyDown={(event) => { if (event.key === "Enter") void rename(); if (event.key === "Escape") setEditing(null); }} aria-label={t("Chat title")} />
          : chat.mine === false ? <strong>{chat.title}</strong>
          : <button type="button" className="asst-title-button" onClick={() => setEditing(chat.title)} title={t("Rename")}><strong>{chat.title}</strong><Pencil size={12} /></button>}
        <small>{chat.mine === false ? t("Shared by {name}", { name: chat.owner_name ?? chat.owner ?? "" }) : chat.profile_name}{chat.ref_view && <> · <RefChip item={chat.ref_view} /></>}{chat.shared?.length ? <> · <Share2 size={11} /> {t("Shared")}</> : null}</small>
      </div>
      <StarButton starred={Boolean(chat.starred)} onToggle={() => { const on = !chat.starred; setChat({ ...chat, starred: on }); collabApi.mark(`chat:${chat.chat_id}`, "star", on).then(onChanged).catch((err) => setError(errorText(err))); }} />
    </header>
    <div className="asst-scroll" ref={scroller} onScroll={(event) => { const box = event.currentTarget; stick.current = box.scrollHeight - box.scrollTop - box.clientHeight < 80; }}>
      {messages.map((message) => message.role === "user"
        ? <div key={message.message_id} className="asst-row asst-mine"><div className="asst-bubble">{message.text}</div></div>
        : <div key={message.message_id} className="asst-row asst-answer"><span className="asst-avatar asst-avatar-sm"><Sparkles /></span><div className="asst-answer-body"><AnswerBody message={message} onRetry={chat.mine !== false && !busy && message === messages[messages.length - 1] && message.state === "failed" ? () => void retry() : undefined} /></div></div>)}
    </div>
    {error && <div className="form-error asst-error"><AlertTriangle size={15} /> {error}</div>}
    {chat.mine === false
      ? <div className="asst-readonly"><span>{t("You are reading a chat {name} shared. To ask more, continue it as your own.", { name: chat.owner_name ?? chat.owner ?? "" })}</span>
        <button type="button" className="button button-primary" disabled={busy} onClick={() => void continueCopy()}><CopyPlus size={15} />{t("Continue in a copy")}</button></div>
      : <Composer busy={busy || working} onSend={send} placeholder={working ? t("Wait for the answer…") : t("Ask a follow-up")} autoFocus />}
  </section>;
}

function NewChat({ status, onStarted }: { status: AssistantStatus; onStarted: () => void }) {
  const ready = status.profiles.filter((item) => item.ready);
  const [profile, setProfile] = useState(ready[0]?.id ?? "");
  const [sent] = useState(fromAddress);
  const admin = canSee(useAccess(), "users");
  const [ref, setRef] = useState(sent.ref);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState(sent.question);
  const starters = sent.starters.length ? sent.starters : STARTERS.map((text) => t(text));
  async function start(text: string) {
    setBusy(true);
    try {
      const started = await assistantApi.start(text, profile, ref);
      onStarted();
      navigate(`/assistant/${started.chat.chat_id}`);
      return true;
    } catch (err) { setError(errorText(err)); return false; } finally { setBusy(false); }
  }
  if (!status.available) return <section className="asst-chat asst-new">
    <div className="asst-center asst-off"><Bot size={34} /><h2>{t("The assistant is off")}</h2><p>{status.reason}</p>
      {admin
        ? <p><a className="button button-secondary" href="/setup/language-model" onClick={(event) => { event.preventDefault(); navigate("/setup/language-model"); }}>{t("Set up the language model")}</a></p>
        : <p className="muted small">{t("An administrator turns it on in Settings › Language models.")}</p>}
    </div>
  </section>;
  return <section className="asst-chat asst-new">
    <div className="asst-hero">
      <span className="asst-avatar asst-avatar-lg"><Sparkles /></span>
      <h2>{t("How can I help?")}</h2>
      <p>{t("Ask about the plant and the platform, or ask it to prepare a block, an action or a rule. The assistant reads only what you may see, and creates nothing until you confirm.")}</p>
      {ready.length > 1 && <label className="asst-profile">{t("Answer as")}
        <select value={profile} onChange={(event) => setProfile(event.target.value)}>{ready.map((item) => <option key={item.id} value={item.id}>{item.name}{item.subject ? ` · ${item.subject}` : ""}</option>)}</select>
      </label>}
      {ref && <div className="asst-about"><span>{t("About")}</span><Hash size={13} /><strong>{ref}</strong><button type="button" className="co-icon" onClick={() => { setRef(""); window.history.replaceState({}, "", window.location.pathname); }} aria-label={t("Remove the reference")}><X size={14} /></button></div>}
      <div className="asst-starters">{starters.map((text) => <button type="button" key={text} onClick={() => setDraft(text)}>{text}</button>)}</div>
    </div>
    {error && <div className="form-error asst-error"><AlertTriangle size={15} /> {error}</div>}
    <Composer busy={busy} onSend={start} placeholder={t("Ask the assistant")} autoFocus initial={draft} />
  </section>;
}

/** `chatId`: an open chat, "new" (a new chat; on a phone, the list hides) or null (the list). */
type ListView = "chats" | "archived" | "shared";

export default function AssistantPage({ chatId }: { chatId: number | "new" | null }) {
  const [status, setStatus] = useState<AssistantStatus | null>(null);
  const [error, setError] = useState("");
  const [shown, setShown] = useState<ListView>("chats");
  const [renaming, setRenaming] = useState<{ id: number; title: string } | null>(null);
  const load = useCallback(() => { assistantApi.status().then((value) => { setStatus(value); setError(""); }).catch((err) => setError(errorText(err))); }, []);
  useEffect(load, [load]);
  const listed = shown === "archived" ? status?.archived ?? [] : shown === "shared" ? status?.shared ?? [] : status?.chats ?? [];
  const groups = useMemo(() => chatSections(listed), [listed]);
  const folders = useMemo(() => [...new Set([...(status?.chats ?? []), ...(status?.archived ?? [])].map((chat) => chat.folder ?? "").filter(Boolean))].sort(), [status]);
  async function saveTitle() {
    if (!renaming) return;
    const { id, title } = renaming;
    setRenaming(null);
    if (!title.trim()) return;
    try { await assistantApi.rename(id, title.trim()); load(); } catch (err) { setError(errorText(err)); }
  }
  async function remove(chat: Chat) {
    if (!window.confirm(t("Delete the chat \"{title}\"?", { title: chat.title }))) return;
    try { await assistantApi.remove(chat.chat_id); if (chat.chat_id === chatId) navigate("/assistant"); load(); } catch (err) { setError(errorText(err)); }
  }
  if (!status) return <div className="asst-page"><div className="asst-center">{error ? <div className="form-error"><AlertTriangle size={15} /> {error}</div> : <LoaderCircle className="spin" />}</div></div>;
  return <div className={`asst-page${chatId !== null ? " asst-has-active" : ""}`}>
    <aside className="asst-list" aria-label={t("Chats")}>
      <header><h1>{t("Assistant")}</h1><button type="button" className="button button-primary asst-new-button" disabled={!status.available} title={status.available ? undefined : status.reason} onClick={() => navigate("/assistant/new")}><MessageSquarePlus size={15} />{t("New chat")}</button></header>
      {error && <div className="form-error"><AlertTriangle size={15} /> {error}</div>}
      <div className="asst-views" role="tablist" aria-label={t("Which chats")}>
        {([["chats", t("Chats")], ["archived", t("Archived")], ["shared", t("Shared with me")]] as Array<[ListView, string]>).map(([key, label]) => {
          const count = key === "archived" ? status.archived?.length ?? 0 : key === "shared" ? status.shared?.length ?? 0 : 0;
          return <button key={key} type="button" role="tab" aria-selected={shown === key} className={shown === key ? "active" : undefined} onClick={() => setShown(key)}>{label}{count > 0 && <span className="asst-count">{count}</span>}</button>;
        })}
      </div>
      {!listed.length && <p className="muted small asst-none">{shown === "archived" ? t("Chats you archive wait here, out of the list.") : shown === "shared" ? t("Chats other people share with you appear here.") : t("Your chats appear here. Each one keeps its own subject.")}</p>}
      {groups.map((group) => <section key={group.key}>
        <h2>{group.folder ? <><FolderInput size={12} /> {group.folder}</> : t(GROUP_LABELS[group.key])}</h2>
        <ul>{group.chats.map((chat) => <li key={chat.chat_id} className={`${chat.chat_id === chatId ? "active" : ""}${chat.unread ? " asst-unread" : ""}`.trim() || undefined}>
          {renaming?.id === chat.chat_id
            ? <input className="asst-rename" autoFocus value={renaming.title} maxLength={120} onChange={(event) => setRenaming({ id: chat.chat_id, title: event.target.value })} onBlur={() => void saveTitle()} onKeyDown={(event) => { if (event.key === "Enter") void saveTitle(); if (event.key === "Escape") setRenaming(null); }} aria-label={t("Chat title")} />
            : <a href={`/assistant/${chat.chat_id}`} onClick={(event) => { event.preventDefault(); navigate(`/assistant/${chat.chat_id}`); }}>
            <strong>{chat.working && <LoaderCircle className="spin" size={12} />}{chat.title}{chat.shared?.length ? <Share2 size={11} aria-label={t("Shared")} /> : null}</strong>
            <small>{chat.mine === false ? t("Shared by {name}", { name: chat.owner_name ?? chat.owner ?? "" }) : chat.profile_name} · {formatAgo(chat.updated_at)}</small>
          </a>}
          <StarButton starred={Boolean(chat.starred)} className={`asst-tool${chat.starred ? " asst-keep" : ""}`} onToggle={() => { collabApi.mark(`chat:${chat.chat_id}`, "star", !chat.starred).then(load).catch((err) => setError(errorText(err))); }} />
          {chat.mine === false
            ? <button type="button" className="asst-tool" onClick={() => void copyText(`${window.location.origin}/assistant/${chat.chat_id}`)} title={t("Copy link")} aria-label={t("Copy link")}><Copy size={14} /></button>
            : <ChatMenu chat={chat} folders={folders} onChanged={load} onRename={() => setRenaming({ id: chat.chat_id, title: chat.title })} onDelete={() => void remove(chat)} />}
        </li>)}</ul>
      </section>)}
    </aside>
    {typeof chatId === "number" ? <ChatPane key={chatId} chatId={chatId} onChanged={load} /> : <NewChat status={status} onStarted={load} />}
  </div>;
}
