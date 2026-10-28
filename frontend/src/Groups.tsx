/** Groups of people (Users › Groups for administrators, /groups/<id> for everyone): a name for
 * several people that every app can notify, filter by or make the owner of something. Each group
 * has a kind (a department, an area of the plant, a discipline or a team) and may have a
 * coordinator, who changes its members (owner, 2026-10-22). Groups form a tree, and a coordinator
 * leads their group and sees the work of every group below it (owner, 2026-10-23). */
import { AlertTriangle, LoaderCircle, MessagesSquare, Pencil, Plus, ShieldCheck, Trash2, UserRound, Users } from "lucide-react";
import { DataTable } from "@plantcraft/ui";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { api } from "./api";
import { collabApi } from "./collabApi";
import { Avatar, Go, PersonLink } from "./collab";
import { groupAndBelow, groupTree, groupsApi, type Group, type GroupDraft, type GroupKind, type GroupList } from "./groupsApi";
import { AssetScopeField } from "./AssetScopeField";
import { t } from "./i18n";
import { navigate } from "./nav";
import { useAdminView } from "./session";
import { UserTabs } from "./Specialists";
import type { WorkspaceUser } from "./types";
import "./access.css";
import { Modal } from "./Modal";

function message(error: unknown) {
  return error instanceof Error ? error.message : t("Couldn't complete the operation.");
}

const KIND_HINTS: Record<GroupKind, string> = {
  department: t("A part of the organization with its manager: operations, maintenance, engineering. Other groups sit under it."),
  area: t("The people of a part of the plant: a unit, an area, a shift."),
  discipline: t("An engineering discipline across the plant: instrumentation, process, electrical."),
  team: t("Any other team: a project, a committee, a contractor's crew."),
};

export function GroupsPage() {
  const isAdmin = useAdminView();
  const [data, setData] = useState<GroupList | null>(null);
  const [people, setPeople] = useState<WorkspaceUser[]>([]);
  const [editing, setEditing] = useState<Group | "new" | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const load = useCallback(() => Promise.all([groupsApi.list(), api.users()]).then(([groups, users]) => { setData(groups); setPeople(users); }).catch((err) => setError(message(err))), []);
  useEffect(() => { if (isAdmin) void load(); }, [isAdmin, load]);
  const tree = useMemo(() => groupTree(data?.groups ?? []), [data]);
  const rows = useMemo(() => tree.map((item) => item.group), [tree]);
  const depth = useMemo(() => new Map(tree.map((item) => [item.group.group_id, item.depth])), [tree]);
  if (!isAdmin) return <div className="module-state module-error"><AlertTriangle /><span>{t("Only admins manage groups.")}</span></div>;

  async function remove(group: Group) {
    if (!window.confirm(t("Delete the group {name}? Its people stay, the groups under it move up a level, and apps that notify it will no longer reach them.", { name: group.name }))) return;
    try { await groupsApi.remove(group.group_id); setNotice(t("{name} was deleted.", { name: group.name })); await load(); } catch (err) { setError(message(err)); }
  }

  return <>
    <div className="page-heading">
      <div><span className="eyebrow"><Users size={14} /> {t("Administration")}</span><h1>{t("People")}</h1><p>{t("Groups gather people by department, area, discipline or team, in a tree: each group may sit under another, and its coordinator sees the work of the groups below. Every app can notify a group or make it the owner of something.")}</p></div>
      <div className="heading-actions"><button className="button button-primary" onClick={() => setEditing("new")} disabled={!data}><Plus size={16} /> {t("New group")}</button></div>
    </div>
    <UserTabs current="groups" />
    {error && <div className="form-error"><AlertTriangle size={15} /> {error}</div>}
    {notice && <div className="ac-notice"><ShieldCheck size={15} /> {notice}</div>}
    {!data && !error && <div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading…")}</span></div>}
    {data && (data.groups.length ? <section className="panel ac-users">
      <DataTable rows={rows} rowKey={(group) => group.group_id} label={t("Groups")}
        searchText={(group) => `${group.name} ${group.description} ${group.parent_name ?? ""} ${group.members.map((member) => member.display_name).join(" ")}`} searchPlaceholder={t("Filter by name or member")}
        columns={[
          { key: "name", label: t("Group"), sort: (group) => group.name, render: (group) => <span className="gr-name" style={{ paddingLeft: `${(depth.get(group.group_id) ?? 0) * 18}px` }}><Go to={`/groups/${encodeURIComponent(group.group_id)}`}><strong>{group.name}</strong></Go>{group.description && <small>{group.description}</small>}</span> },
          { key: "parent", label: t("Under"), sort: (group) => group.parent_name ?? "", filter: { value: (group) => group.parent_name ?? t("Top level") }, render: (group) => group.parent_name ? <Go to={`/groups/${encodeURIComponent(group.parent_id ?? "")}`}>{group.parent_name}</Go> : <span className="muted">—</span> },
          { key: "kind", label: t("Kind"), sort: (group) => group.kind_label, filter: { value: (group) => group.kind_label }, render: (group) => <span className={`gr-kind gr-kind-${group.kind}`}>{group.kind_label}</span> },
          { key: "members", label: t("Members"), sort: (group) => group.members.length, render: (group) => <span className="gr-members">{group.members.slice(0, 4).map((member) => <Avatar key={member.username} name={member.display_name} size="sm" />)}<span>{group.members.length === 1 ? t("1 person") : t("{count} people", { count: group.members.length })}</span></span> },
          { key: "coordinator", label: t("Coordinator"), sort: (group) => group.coordinator_name ?? "", filter: { value: (group) => group.coordinator_name ?? t("None") }, render: (group) => group.coordinator ? <PersonLink username={group.coordinator} name={group.coordinator_name} /> : <span className="muted">—</span> },
          { key: "actions", label: <span className="sr-only">{t("Actions")}</span>, className: "ac-row-actions", render: (group) => <>
            <button className="icon-button" title={t("Edit")} aria-label={t("Edit {name}", { name: group.name })} onClick={() => setEditing(group)}><Pencil size={15} /></button>
            <button className="icon-button" title={t("Delete")} aria-label={t("Delete {name}", { name: group.name })} onClick={() => void remove(group)}><Trash2 size={15} /></button>
          </> },
        ]} />
    </section> : <section className="panel"><div className="empty-state"><Users /><strong>{t("No groups yet")}</strong><p>{t("Create one per area of the plant (Unit 100 operations) or per discipline (Instrumentation and control), so alarms and other notices reach the right people.")}</p></div></section>)}
    {editing && data && <GroupForm kinds={data.kinds} people={people} groups={data.groups} group={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={(group, created) => { setEditing(null); setNotice(created ? t("{name} was created.", { name: group.name }) : t("{name} was updated.", { name: group.name })); void load(); }} />}
  </>;
}

/** Pick people from a list with a filter: who is in shows first. */
export function MemberPicker({ people, value, onChange, locked }: { people: WorkspaceUser[]; value: string[]; onChange: (value: string[]) => void; locked?: string | null }) {
  const [text, setText] = useState("");
  const shown = useMemo(() => {
    const needle = text.trim().toLowerCase();
    return people
      .filter((person) => !needle || `${person.display_name} ${person.username} ${person.role}`.toLowerCase().includes(needle))
      .sort((a, b) => Number(value.includes(b.username)) - Number(value.includes(a.username)) || a.display_name.localeCompare(b.display_name));
  }, [people, text, value]);
  return <div className="gr-picker">
    <input value={text} onChange={(event) => setText(event.target.value)} placeholder={t("Find a person")} aria-label={t("Find a person")} />
    <ul>{shown.map((person) => { const on = value.includes(person.username); return <li key={person.username}><label className="ac-check">
      <input type="checkbox" checked={on} disabled={person.username === locked} onChange={() => onChange(on ? value.filter((name) => name !== person.username) : [...value, person.username])} />
      <Avatar name={person.display_name} size="sm" /><span><strong>{person.display_name}</strong><small>{person.role || `@${person.username}`}</small></span>
    </label></li>; })}</ul>
    <small className="muted">{value.length === 1 ? t("1 person chosen") : t("{count} people chosen", { count: value.length })}</small>
  </div>;
}

function GroupForm({ kinds, people, groups, group, onClose, onSaved }: { kinds: GroupList["kinds"]; people: WorkspaceUser[]; groups: Group[]; group: Group | null; onClose: () => void; onSaved: (group: Group, created: boolean) => void }) {
  const [draft, setDraft] = useState<GroupDraft>({ name: group?.name ?? "", kind: group?.kind ?? "area", description: group?.description ?? "", asset_id: group?.asset_id ?? null, coordinator: group?.coordinator ?? null, members: group?.members.map((member) => member.username) ?? [], parent_id: group?.parent_id ?? null, asset_scope: group?.asset_scope ?? null });
  // A group never sits under itself or under a group below it.
  const parents = useMemo(() => { const below = group ? groupAndBelow(groups, group.group_id) : new Set<string>(); return groupTree(groups).filter((item) => !below.has(item.group.group_id)); }, [groups, group]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const saved = group ? await groupsApi.update(group.group_id, draft) : await groupsApi.create(draft);
      onSaved(saved, !group);
    } catch (err) { setError(message(err)); setBusy(false); }
  }
  return <Modal label={group ? group.name : t("New group")} eyebrow={<><Users size={13} /> {t("Group")}</>} title={group ? group.name : t("New group")} description={t("Apps notify the whole group. Its coordinator leads it: they change who is in it and see the work of the groups below.")} onClose={onClose} className="ac-form">
    <form onSubmit={submit}>
      <div className="form-grid">
        {error && <div className="form-error field-span"><AlertTriangle size={15} /> {error}</div>}
        <label>{t("Name")}<input required value={draft.name} maxLength={120} placeholder={t("E.g. Unit 100 operations")} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label>
        <label>{t("Kind")}<select value={draft.kind} onChange={(event) => setDraft({ ...draft, kind: event.target.value as GroupKind })}>{kinds.map((kind) => <option key={kind.id} value={kind.id}>{kind.label}</option>)}</select></label>
        <p className="ac-hint field-span">{KIND_HINTS[draft.kind]}</p>
        <label className="field-span">{t("Under")}<select value={draft.parent_id ?? ""} onChange={(event) => setDraft({ ...draft, parent_id: event.target.value || null })}>
          <option value="">{t("Top level")}</option>
          {parents.map((item) => <option key={item.group.group_id} value={item.group.group_id}>{`${"— ".repeat(item.depth)}${item.group.name}`}</option>)}
        </select></label>
        <label className="field-span">{t("Description")}<input value={draft.description} maxLength={500} placeholder={t("What the group does, its shift or its contact")} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></label>
        <label>{t("Coordinator (leader)")}<select value={draft.coordinator ?? ""} onChange={(event) => { const coordinator = event.target.value || null; setDraft({ ...draft, coordinator, members: coordinator && !draft.members.includes(coordinator) ? [...draft.members, coordinator] : draft.members }); }}>
          <option value="">{t("None")}</option>
          {people.map((person) => <option key={person.username} value={person.username}>{person.display_name}</option>)}
        </select></label>
        {draft.kind === "area" && <label>{t("Asset it covers (optional)")}<input value={draft.asset_id ?? ""} maxLength={300} placeholder={t("E.g. the unit's asset id")} onChange={(event) => setDraft({ ...draft, asset_id: event.target.value || null })} /></label>}
        <AssetScopeField legend={t("Assets members see")} hint={t("Members see only these assets, their signals and what apps publish about them. A person in several limited groups sees all of their assets; administrators always see the whole plant.")} value={draft.asset_scope ?? null} onChange={(asset_scope) => setDraft({ ...draft, asset_scope })} />
        <fieldset className="field-span ac-fieldset"><legend>{t("Members")}</legend><MemberPicker people={people} value={draft.members} locked={draft.coordinator} onChange={(members) => setDraft({ ...draft, members })} /></fieldset>
      </div>
      <footer><button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button><button className="button button-primary" disabled={busy}>{busy && <LoaderCircle className="spin" size={15} />} {group ? t("Save") : t("Create group")}</button></footer>
    </form>
  </Modal>;
}

/** A group's page: who is in it, who coordinates it; the coordinator changes the members here. */
export function GroupPage({ groupId }: { groupId: string }) {
  const [group, setGroup] = useState<Group | null>(null);
  const [people, setPeople] = useState<WorkspaceUser[]>([]);
  const [editing, setEditing] = useState(false);
  const [members, setMembers] = useState<string[]>([]);
  const [error, setError] = useState("");
  const load = useCallback(() => groupsApi.get(groupId).then((value) => { setGroup(value); setError(""); }).catch((err) => setError(message(err))), [groupId]);
  useEffect(() => { void load(); }, [load]);
  if (error && !group) return <div className="module-state module-error"><AlertTriangle /><span>{error}</span></div>;
  if (!group) return <div className="module-state"><LoaderCircle className="spin" /></div>;
  async function startEditing() {
    try { setPeople(await api.users()); setMembers(group!.members.map((member) => member.username)); setEditing(true); } catch (err) { setError(message(err)); }
  }
  async function save() {
    try { setGroup(await groupsApi.setMembers(groupId, members)); setEditing(false); setError(""); } catch (err) { setError(message(err)); }
  }
  async function talk() {
    try { const conversation = await collabApi.groupConversation(groupId); navigate(`/messages/${encodeURIComponent(String(conversation.conversation_id))}`); } catch (err) { setError(message(err)); }
  }
  return <>
    <div className="page-heading">
      <div><span className="eyebrow"><Users size={14} /> {t("Group")} · {group.kind_label}{(group.path ?? []).map((item) => <span key={item.group_id}> · <Go to={`/groups/${encodeURIComponent(item.group_id)}`}>{item.name}</Go></span>)}</span><h1>{group.name}</h1>{group.description && <p>{group.description}</p>}</div>
      <div className="heading-actions">
        {group.is_member && <button className="button button-primary" onClick={() => void talk()}><MessagesSquare size={15} /> {t("Group conversation")}</button>}
        {group.can_edit_members && !editing && <button className="button button-secondary" onClick={() => void startEditing()}><Pencil size={15} /> {t("Change members")}</button>}
        {group.can_manage && <button className="button button-secondary" onClick={() => navigate("/users/groups")}>{t("All groups")}</button>}
      </div>
    </div>
    {error && <div className="form-error"><AlertTriangle size={15} /> {error}</div>}
    <div className="pp-grid">
      <section className="panel">
        <h2 className="section-title"><Users size={15} /> {t("Members")}</h2>
        {editing ? <div className="form-grid gr-edit"><MemberPicker people={people} value={members} locked={group.coordinator} onChange={setMembers} /><footer><button type="button" className="button button-secondary" onClick={() => setEditing(false)}>{t("Cancel")}</button><button type="button" className="button button-primary" onClick={() => void save()}>{t("Save")}</button></footer></div>
          : group.members.length ? <ul className="gr-list">{group.members.map((member) => <li key={member.username}><Avatar name={member.display_name} size="sm" /><PersonLink username={member.username} name={member.display_name} />{member.username === group.coordinator && <span className="gr-kind gr-kind-team">{t("Coordinator")}</span>}{!member.active && <span className="muted">{t("Deactivated")}</span>}</li>)}</ul>
          : <p className="muted">{t("Nobody yet.")}</p>}
      </section>
      <section className="panel">
        <h2 className="section-title"><UserRound size={15} /> {t("About")}</h2>
        <dl className="pp-facts">
          <div><dt>{t("Kind")}</dt><dd>{group.kind_label}</dd></div>
          <div><dt>{t("Coordinator (leader)")}</dt><dd>{group.coordinator ? <PersonLink username={group.coordinator} name={group.coordinator_name} /> : t("None")}</dd></div>
          <div><dt>{t("Under")}</dt><dd>{group.parent_id ? <Go to={`/groups/${encodeURIComponent(group.parent_id)}`}>{group.parent_name}</Go> : t("Top level")}</dd></div>
          {(group.subgroups ?? []).length > 0 && <div><dt>{t("Groups below")}</dt><dd>{(group.subgroups ?? []).map((item, index) => <span key={item.group_id}>{index > 0 && ", "}<Go to={`/groups/${encodeURIComponent(item.group_id)}`}>{item.name}</Go></span>)}</dd></div>}
          {group.asset_id && <div><dt>{t("Asset")}</dt><dd><Go to={`/assets/${encodeURIComponent(group.asset_id)}`}>{group.asset_id}</Go></dd></div>}
          <div><dt>{t("Reference")}</dt><dd><code>group:{group.group_id}</code></dd></div>
        </dl>
        <p className="muted">{t("Apps send their notifications to this group by its reference; everyone in it receives them in Messages.")}</p>
      </section>
    </div>
  </>;
}

export default GroupsPage;
