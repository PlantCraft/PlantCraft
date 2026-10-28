/**
 * Desk › Team (owner, round 7, 2026-10-24): "how is my group today, and who can take this?".
 * Every member sees their groups (a leader also those under the groups they lead): its people
 * (role, away or busy by their calendar without saying why, open and late actions, a message
 * button), its actions as a board by status or by person (a leader drags a card to hand it to
 * someone or to change its status), the week ahead, the shift handover note of the day (a note
 * shared with the group), the assets its people follow that are in alarm, and its shared lists.
 */
import { statusVar } from "@plantcraft/ui";
import { CalendarDays, ClipboardList, ListTodo, MessageSquare, NotebookPen, Users } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type DragEvent } from "react";
import { Go, errorText, shortWhen } from "./collab";
import { collabApi } from "./collabApi";
import { PageHeading } from "./DeskPages";
import { deskApi, type Team, type TeamCard, type TeamGlance, type TeamGroup, type TeamPerson } from "./deskApi";
import { language, t } from "./i18n";
import { navigate } from "./nav";
import "./desk.css";

type BoardBy = "status" | "person";

/** The board's columns: by status, or one per person (the group itself for cards with no owner). */
export function boardColumns(group: Pick<TeamGroup, "board" | "statuses" | "people">, by: BoardBy): Array<{ id: string; label: string; cards: TeamCard[] }> {
  if (by === "status") return group.statuses.map((status) => ({ ...status, cards: group.board.filter((card) => card.status === status.id) }));
  const people = group.people.map((person) => ({ id: person.username, label: person.display_name, cards: group.board.filter((card) => card.owner === person.username) }));
  const nobody = group.board.filter((card) => !card.owner || !group.people.some((person) => person.username === card.owner));
  return [{ id: "", label: t("The group"), cards: nobody }, ...people];
}

function dayLabel(day: string, today: string): string {
  if (day === today) return t("Today");
  return new Date(`${day}T12:00:00`).toLocaleDateString(language, { weekday: "long", day: "numeric", month: "short" });
}

function Board({ group, onMoved, onError }: { group: TeamGroup; onMoved: () => void; onError: (text: string) => void }) {
  const [by, setBy] = useState<BoardBy>("status");
  const [over, setOver] = useState<string | null>(null);
  const columns = useMemo(() => boardColumns(group, by), [group, by]);
  async function drop(column: string, event: DragEvent<HTMLElement>) {
    event.preventDefault();
    setOver(null);
    const id = Number(event.dataTransfer.getData("text/plain"));
    const card = group.board.find((item) => item.action_id === id);
    if (!card) return;
    const change = by === "status" ? { action_id: id, status: column } : { action_id: id, owner: column || null };
    if (by === "status" ? card.status === column : (card.owner ?? "") === column) return;
    try { await deskApi.assign(group.group_id, change); onMoved(); } catch (err) { onError(errorText(err)); }
  }
  return <section className="panel dk-team-board" aria-label={t("Group board")}>
    <header className="dk-team-head">
      <h2><ClipboardList size={15} aria-hidden="true" /> {t("Group board")}</h2>
      <span className="dk-team-switch" role="group" aria-label={t("Columns")}>
        <button type="button" className={`dk-chip${by === "status" ? " on" : ""}`} aria-pressed={by === "status"} onClick={() => setBy("status")}>{t("By status")}</button>
        <button type="button" className={`dk-chip${by === "person" ? " on" : ""}`} aria-pressed={by === "person"} onClick={() => setBy("person")}>{t("By person")}</button>
      </span>
    </header>
    {group.leader && <p className="muted small">{t("Drag a card to hand it to someone else or to change its status.")}</p>}
    <div className="dk-team-columns">
      {columns.map((column) => <section key={column.id || "group"} className={`dk-team-column${over === column.id ? " over" : ""}`} aria-label={column.label} data-column={column.id}
        onDragOver={group.leader ? (event) => { event.preventDefault(); setOver(column.id); } : undefined}
        onDragLeave={() => setOver(null)} onDrop={group.leader ? (event) => void drop(column.id, event) : undefined}>
        <h3>{column.label} <small>{column.cards.length}</small></h3>
        {column.cards.map((card) => <article key={card.action_id} className={`dk-team-card${card.late ? " late" : ""}`} draggable={group.leader} data-action={card.action_id}
          onDragStart={(event) => { event.dataTransfer.setData("text/plain", String(card.action_id)); event.dataTransfer.effectAllowed = "move"; }}>
          <Go to={card.href}>{card.title}</Go>
          <small className="muted">{[by === "status" ? card.owner_name ?? t("The group") : card.status_label, card.due_at ? (card.late ? t("Late · {day}", { day: card.due_at }) : card.due_at) : null].filter(Boolean).join(" · ")}</small>
        </article>)}
        {!column.cards.length && <p className="muted small">{t("Nothing here.")}</p>}
      </section>)}
    </div>
  </section>;
}

const AVAILABILITY = { away: t("Away today"), busy: t("Busy now"), "": t("Available") };

/** A person's state as one dot: late work red, away or busy amber, otherwise green. */
function personDot(person: TeamPerson): string {
  return statusVar(person.late ? "alarm" : person.availability ? "warning" : "ok");
}

/** Every group at a glance (round 8): a card per group with its people and how each is doing
 * today; a group's name opens its full page. A leader sees the groups under theirs, an
 * administrator every group. */
function Overview({ groups, onOpen }: { groups: TeamGlance[]; onOpen: (groupId: string) => void }) {
  const people = groups.reduce((sum, group) => sum + group.people.length, 0);
  const away = groups.reduce((sum, group) => sum + group.away, 0);
  const late = groups.reduce((sum, group) => sum + group.late, 0);
  return <>
    <p className="muted small dk-team-sub">{[t("{count} groups", { count: groups.length }), t("{count} people", { count: people }), away ? t("{count} away today", { count: away }) : null, late ? t("{count} late actions", { count: late }) : null].filter(Boolean).join(" · ")}</p>
    <div className="dk-team-glance">
      {groups.map((group) => <section key={group.group_id} className="panel pc-wg-list dk-team-glance-card" aria-label={group.name}>
        <header className="dk-team-glance-head">
          <button type="button" className="dk-team-glance-name" onClick={() => onOpen(group.group_id)}>{group.name}</button>
          <span className="act-counts">
            {group.late > 0 && <span className="act-count act-count-late" title={t("{count} late", { count: group.late })}>{t("{count} late", { count: group.late })}</span>}
            <span className="act-count" title={t("{count} open actions", { count: group.open })}>{group.open}</span>
          </span>
        </header>
        <small className="muted">{[group.kind_label, group.coordinator_name ? t("Led by {name}", { name: group.coordinator_name }) : null].filter(Boolean).join(" · ")}</small>
        {!group.people.length && <p className="muted small">{t("Nobody in this group yet.")}</p>}
        {group.people.map((person) => <div key={person.username} className="pc-wg-row dk-team-person">
          <span className="pc-wg-dot" style={{ background: personDot(person) }} aria-hidden="true" />
          <span className="pc-wg-row-text">
            <b><Go to={`/people/${person.username}`}>{person.display_name}</Go>{person.leader ? <small className="dk-team-role"> {t("Leader")}</small> : null}</b>
            <small>{[AVAILABILITY[person.availability], t("{count} open", { count: person.open }), person.late ? t("{count} late", { count: person.late }) : null].filter(Boolean).join(" · ")}</small>
          </span>
        </div>)}
      </section>)}
    </div>
  </>;
}

export function TeamPage() {
  const [chosen, setChosen] = useState<string | null>(() => new URLSearchParams(window.location.search).get("group"));
  const [data, setData] = useState<Team | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    deskApi.team(chosen ?? undefined).then((value) => { setData(value); setError(""); }).catch((err) => setError(errorText(err)));
  }, [chosen]);
  useEffect(load, [load]);
  useEffect(() => {
    if (data?.group) window.history.replaceState(window.history.state, "", `/team?group=${encodeURIComponent(data.group.group_id)}`);
    else if (data?.overview) window.history.replaceState(window.history.state, "", "/team?group=all");
  }, [data?.group, data?.overview]);
  async function message(username: string) {
    try { const made = await collabApi.startConversation({ members: [username] }); navigate(`/messages/${made.conversation.conversation_id}`); } catch (err) { setError(errorText(err)); }
  }
  async function handover(group: TeamGroup) {
    try { const note = await deskApi.handover(group.group_id); navigate(`/notes?note=${note.note_id}`); } catch (err) { setError(errorText(err)); }
  }
  const group = data?.group ?? null;
  const days = useMemo(() => {
    const byDay = new Map<string, TeamGroup["agenda"]>();
    for (const item of group?.agenda ?? []) byDay.set(item.day, [...(byDay.get(item.day) ?? []), item]);
    return [...byDay.entries()];
  }, [group]);
  const availability = AVAILABILITY;
  return <>
    <PageHeading eyebrow={t("Desk")} title={t("Team")} description={t("How your group is doing today and who can take what: its people, its actions, the week ahead and the shift handover.")}
      action={data && data.groups.length > 1 ? <label className="dk-team-pick">{t("Group")}<select id="dk-team-group" value={group?.group_id ?? "all"} onChange={(event) => setChosen(event.target.value)}>
        <option value="all">{t("All groups")}</option>
        {data.groups.map((item) => <option key={item.group_id} value={item.group_id}>{item.name}{item.leader && item.mine !== false ? ` · ${t("you lead")}` : ""}</option>)}
      </select></label> : undefined} />
    {error && <div className="form-error">{error}</div>}
    {data?.overview && <Overview groups={data.overview} onOpen={setChosen} />}
    {data && !group && !data.overview && <section className="panel"><p className="muted"><Users size={15} aria-hidden="true" /> {t("You are in no group yet. An administrator puts people in groups in People › Groups.")}</p></section>}
    {group && <>
      <p className="muted small dk-team-sub">{[group.kind_label, group.coordinator_name ? t("Led by {name}", { name: group.coordinator_name }) : null, group.leader ? (data?.groups.find((item) => item.group_id === group.group_id)?.mine === false ? t("You see every group as an administrator or a leader above it") : t("You lead this group")) : null].filter(Boolean).join(" · ")}</p>
      <div className="dk-team">
        <section className="panel pc-wg-list" aria-label={t("People")}>
          <h2>{t("People")}</h2>
          {group.people.map((person) => <div key={person.username} className="pc-wg-row dk-team-person">
            <span className="pc-wg-dot" style={{ background: personDot(person) }} aria-hidden="true" />
            <span className="pc-wg-row-text">
              <b><Go to={`/people/${person.username}`}>{person.display_name}</Go>{person.leader ? <small className="dk-team-role"> {t("Leader")}</small> : null}</b>
              <small>{[availability[person.availability], t("{count} open", { count: person.open }), person.late ? t("{count} late", { count: person.late }) : null].filter(Boolean).join(" · ")}</small>
            </span>
            {!person.you && <button type="button" className="pcs-icon-button" onClick={() => void message(person.username)} aria-label={t("Message {name}", { name: person.display_name })} title={t("Message {name}", { name: person.display_name })}><MessageSquare size={15} /></button>}
          </div>)}
        </section>
        <section className="panel pc-wg-list" aria-label={t("Shift handover")}>
          <h2>{t("Shift handover")}</h2>
          <p className="muted small">{t("One note a day, shared with the group: what happened and what comes next, read by whoever comes in.")}</p>
          <button type="button" className="button button-primary button-small" onClick={() => void handover(group)}><NotebookPen size={14} /> {group.handover ? t("Open today's handover") : t("Write today's handover")}</button>
          {group.handovers.filter((item) => item.day !== group.day).map((item) => <Go key={item.note_id} to={`/notes?note=${item.note_id}`} className="pc-wg-row">
            <span className="pc-wg-row-text"><b>{dayLabel(item.day, group.day)}</b><small>{item.snippet || shortWhen(item.updated_at)}</small></span>
          </Go>)}
        </section>
        <section className="panel pc-wg-list" aria-label={t("The week")}>
          <h2><CalendarDays size={13} aria-hidden="true" /> {t("The week")}</h2>
          {!days.length && <p className="muted small">{t("Nothing dated this week.")}</p>}
          {days.map(([day, items]) => <div key={day} className="dk-team-day">
            <h3>{dayLabel(day, group.day)}</h3>
            {items.map((item, index) => <div key={`${item.kind}:${item.title}:${index}`} className="dk-team-agenda">
              <span className="pc-wg-dot" style={{ background: statusVar(item.late ? "alarm" : item.kind === "away" ? "unknown" : "ok") }} aria-hidden="true" />
              {item.href ? <Go to={item.href}>{item.title}</Go> : <span>{item.title}</span>}
              {item.who && item.kind !== "away" && <small className="muted">{item.who}</small>}
            </div>)}
          </div>)}
        </section>
      </div>
      <Board group={group} onMoved={load} onError={setError} />
      <div className="dk-team">
        <section className="panel pc-wg-list" aria-label={t("Assets in alarm")}>
          <h2>{t("Assets in alarm")}</h2>
          {!group.assets.length && <p className="muted small">{t("Nothing the group follows is in alarm.")}</p>}
          {group.assets.map((asset) => <Go key={asset.ref} to={asset.href ?? "/assets"} className="pc-wg-row">
            <span className="pc-wg-dot" style={{ background: statusVar(asset.status) }} aria-hidden="true" />
            <span className="pc-wg-row-text"><b>{asset.name}</b><small>{[asset.summary, t("Followed by {names}", { names: asset.followers.join(", ") })].filter(Boolean).join(" · ")}</small></span>
          </Go>)}
        </section>
        <section className="panel pc-wg-list" aria-label={t("Shared lists")}>
          <h2><ListTodo size={13} aria-hidden="true" /> {t("Shared lists")}</h2>
          {!group.lists.length && <p className="muted small">{group.leader ? t("No shared list yet: make one in To-do › New list.") : t("No shared list yet.")}</p>}
          {group.lists.map((list) => <Go key={list.list_id} to={`/todo?list=${list.list_id}`} className="pc-wg-row">
            <i className="dk-todo-dot" style={{ background: list.color }} aria-hidden="true" />
            <span className="pc-wg-row-text"><b>{list.name}</b><small>{t("{count} open", { count: list.open })}</small></span>
          </Go>)}
        </section>
      </div>
    </>}
  </>;
}
