/**
 * Who receives something, or who owns it: people and groups of the platform, picked the same way
 * in every app (an alarm's owner, a notification policy's recipients). The value is a list of
 * references, `user:<username>` and `group:<id>`, as API v1 notifications take them; the apps
 * read the people and groups from `GET /api/v1/people` and `GET /api/v1/groups`.
 */
import { Users, X } from "lucide-react";
import { useMemo, useState } from "react";
import { t } from "./i18n.js";

export interface PersonOption { username: string; name: string; role?: string | null; job_title?: string | null }
export interface GroupOption { id: string; name: string; kind?: string | null; members?: string[] }

export interface RecipientPickerProps {
  value: string[];
  onChange: (value: string[]) => void;
  people: PersonOption[];
  groups: GroupOption[];
  label: string;
  /** One recipient only (an owner): picking another replaces it. */
  single?: boolean;
  placeholder?: string;
}

const KIND_WORDS: Record<string, string> = { area: "Area", discipline: "Discipline", team: "Team" };

/** "Ana Lima", "Unit 100 operations (group)" or the reference itself when nobody matches. */
export function recipientLabel(ref: string, people: PersonOption[], groups: GroupOption[]): string {
  const [kind, ...rest] = ref.split(":");
  const id = rest.join(":");
  if (kind === "user") return people.find((person) => person.username === id)?.name ?? id;
  if (kind === "group") {
    const group = groups.find((item) => item.id === id);
    return group ? t("{name} (group)", { name: group.name }) : id;
  }
  return ref;
}

/** Everyone a list of references reaches: the people named and every member of the groups. */
export function recipientPeople(value: string[], groups: GroupOption[]): string[] {
  const found: string[] = [];
  for (const ref of value) {
    const [kind, ...rest] = ref.split(":");
    const id = rest.join(":");
    if (kind === "user") found.push(id);
    if (kind === "group") found.push(...(groups.find((group) => group.id === id)?.members ?? []));
  }
  return [...new Set(found)];
}

type Choice = { ref: string; title: string; detail: string; group: boolean };

export function RecipientPicker({ value, onChange, people, groups, label, single, placeholder }: RecipientPickerProps) {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const choices = useMemo<Choice[]>(() => {
    const needle = text.trim().toLowerCase();
    const all: Choice[] = [
      ...groups.map((group) => ({ ref: `group:${group.id}`, title: group.name, detail: [group.kind ? t(KIND_WORDS[group.kind] ?? group.kind) : "", group.members ? t("{count} people", { count: group.members.length }) : ""].filter(Boolean).join(" · "), group: true })),
      ...people.map((person) => ({ ref: `user:${person.username}`, title: person.name, detail: [person.job_title, person.role].filter(Boolean).join(" · ") || `@${person.username}`, group: false })),
    ];
    return all.filter((choice) => !value.includes(choice.ref) && (!needle || `${choice.title} ${choice.detail} ${choice.ref}`.toLowerCase().includes(needle))).slice(0, 30);
  }, [groups, people, text, value]);
  function pick(ref: string) {
    onChange(single ? [ref] : [...value, ref]);
    setText("");
    setOpen(false);
  }
  return <div className="pc-recipients">
    {value.length > 0 && <ul className="pc-recipient-chips" aria-label={label}>{value.map((ref) => <li key={ref} className={ref.startsWith("group:") ? "pc-recipient-group" : ""}>
      {ref.startsWith("group:") && <Users size={13} aria-hidden="true" />}
      <span>{recipientLabel(ref, people, groups)}</span>
      <button type="button" aria-label={t("Remove {name}", { name: recipientLabel(ref, people, groups) })} onClick={() => onChange(value.filter((item) => item !== ref))}><X size={13} /></button>
    </li>)}</ul>}
    {(!single || value.length === 0) && <div className="pc-search">
      <input aria-label={label} value={text} placeholder={placeholder ?? t("Find a person or a group")} onFocus={() => setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 150)} onChange={(event) => { setText(event.target.value); setOpen(true); }} />
      {open && choices.length > 0 && <ul>{choices.map((choice) => <li key={choice.ref}><button type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => pick(choice.ref)}>
        <span>{choice.group && <Users size={13} aria-hidden="true" />} {choice.title}</span><small>{choice.detail}</small></button></li>)}</ul>}
    </div>}
    {single && value.length > 0 && <button type="button" className="pc-recipient-change" onClick={() => onChange([])}>{t("Change")}</button>}
  </div>;
}
