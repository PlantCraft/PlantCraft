/** The Overview's (/admin) answer to "is the installation healthy?": the System
 * card (open problems, services, free disk, last backup, version, who signed in today) and the
 * last changes of the audit log. Both read what System health, Backups, Updates and the audit log
 * already keep (/api/home/system, /api/audit) and draw in the suite's widget shapes. */
import { appLabel, FactsBody, formatDate, formatNumber, ListBody, type WidgetData, type WidgetFact, type WidgetItem } from "@plantcraft/ui";
import { LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { requestJson } from "./api";
import type { AuditRow } from "./AuditLog";
import { t } from "./i18n";
import type { WorkspaceUser } from "./types";

const EVERY_MS = 60_000;
const CHANGES = 6;

export interface SystemFacts {
  admin: boolean;
  watching: boolean;
  open: number;
  services: { running: number; total: number } | null;
  version: string;
  update: { from?: string; to?: string; state?: string; at?: string } | null;
  /** Administrators only, like the System health page. */
  disk?: { free_bytes: number | null; free_pct: number | null; days_left: number | null; state: string } | null;
  backup?: { name: string; at: string; state: string } | null;
  signed_in_today?: number;
}

/** "14:05" today, "26 Oct, 14:05" before, on the person's clock. */
export function clockText(at: string, now: number = Date.now()): string {
  const day = (value: string | number) => formatDate(value, { dateStyle: "short" });
  return day(at) === day(now) ? formatDate(at, { hour: "2-digit", minute: "2-digit" }) : formatDate(at, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function diskText(disk: NonNullable<SystemFacts["disk"]>): string {
  if (disk.free_bytes == null) return "—";
  const gb = disk.free_bytes / 2 ** 30;
  const size = `${formatNumber(gb, gb >= 100 ? 0 : 1)} GB`;
  return disk.free_pct == null ? size : `${size} · ${formatNumber(disk.free_pct, 0)} %`;
}

/** The System card as a facts widget: the head says whether anything is open, the facts what an
 * administrator checks first (others see the version and the services). */
export function systemWidget(system: SystemFacts, now: number = Date.now()): Extract<WidgetData, { kind: "facts" }> {
  const services = system.services;
  const down = services ? services.total - services.running : 0;
  const rolledBack = system.update?.state === "returned" || system.update?.state === "rolled-back";
  const version: WidgetFact = { label: t("Version"), value: rolledBack ? t("{version}, update rolled back", { version: system.version }) : system.version || "—", state: rolledBack ? "warning" : null };
  const running: WidgetFact = { label: t("Services"), value: services ? t("{running} of {total} running", services) : "—", state: services ? (down ? "alarm" : "ok") : null };
  const facts: WidgetFact[] = system.admin ? [
    { label: t("Free disk"), value: system.disk ? diskText(system.disk) : "—", state: system.disk?.state ?? null },
    { label: t("Last backup"), value: !system.backup ? t("None yet") : system.backup.state === "alarm" ? t("Failed {date}", { date: clockText(system.backup.at, now) }) : clockText(system.backup.at, now), state: system.backup?.state ?? null },
    version,
    { label: t("Signed in today"), value: system.signed_in_today ?? 0 },
  ] : [version, running];
  const detail = services ? t("{running} of {total} services running", services) : system.watching ? "" : t("Services are not watched here (no installer)");
  // The head says the worst of it: an open problem, a service down, or a fact in alarm or warning.
  const states = [system.open || down ? "alarm" : "ok", ...facts.map((fact) => fact.state)];
  const worst = states.includes("alarm") ? "alarm" : states.includes("warning") ? "warning" : "ok";
  return {
    kind: "facts",
    title: system.open ? t("{count} problems open", { count: system.open }) : worst === "alarm" ? t("Needs attention") : worst === "warning" ? t("Worth a look") : t("Healthy"),
    state: worst,
    detail: system.admin ? detail : null,
    facts,
    href: "/health",
  };
}

const VERBS = new Set(["create", "update", "delete", "revoke", "rotate", "restore", "rename", "move", "start", "stop", "set", "add", "remove", "import", "export", "enable", "disable", "approve", "close", "open"]);

/** An audit action in words: "app_key.create" is "Create app key", "operations.backup" "Operations
 * backup". */
export function actionText(action: string): string {
  const words = action.split(/[._]+/).filter(Boolean);
  if (!words.length) return action;
  const last = words[words.length - 1];
  const ordered = VERBS.has(last) ? [last, ...words.slice(0, -1)] : words;
  const text = ordered.join(" ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** A subject without its kind ("app:linkcraft" is "Analytics", "suite:operations" "operations"). */
function subjectText(subject: string): string {
  const [kind, ...rest] = subject.split(":");
  if (!rest.length) return subject;
  const id = rest.join(":");
  return kind === "app" ? appLabel(id, id) : id;
}

/** The audit log's last changes (sign-ins left out), newest first: what changed, who, when. */
export function changesWidget(rows: AuditRow[], users: WorkspaceUser[], now: number = Date.now()): Extract<WidgetData, { kind: "list" }> {
  const name = (username: string) => users.find((user) => user.username === username)?.display_name || username;
  const items: WidgetItem[] = rows.map((row) => ({
    label: row.subject ? `${actionText(row.action)} · ${subjectText(row.subject)}` : actionText(row.action),
    detail: row.app_id && row.app_id !== "processcraft" ? `${name(row.username)} · ${appLabel(row.app_id, row.app_id)}` : name(row.username),
    value: clockText(row.at, now),
    href: "/setup/audit",
  }));
  return { kind: "list", items, href: "/setup/audit", empty: t("Nothing changed in the last 30 days.") };
}

/** Reads `load` now and every minute while the card is on the page. */
function usePolled<T>(load: () => Promise<T>): { value: T | null; error: string } {
  const [value, setValue] = useState<T | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    const read = () => load().then((next) => { if (alive) { setValue(next); setError(""); } }).catch((err) => { if (alive) setError(err instanceof Error ? err.message : String(err)); });
    void read();
    const timer = window.setInterval(read, EVERY_MS);
    return () => { alive = false; window.clearInterval(timer); };
  }, []);
  return { value, error };
}

function Waiting({ error }: { error: string }) {
  return error ? <p className="form-error">{error}</p> : <LoaderCircle size={16} className="spin" aria-label={t("Loading")} />;
}

export function SystemWidget({ w, h }: { w: number; h: number }) {
  const { value, error } = usePolled(() => requestJson<SystemFacts>("/api/home/system"));
  return value ? <FactsBody data={systemWidget(value)} w={w} h={h} /> : <Waiting error={error} />;
}

export function RecentChanges({ users, rows }: { users: WorkspaceUser[]; rows: number }) {
  const { value, error } = usePolled(() => requestJson<{ rows: AuditRow[] }>(`/api/audit?kind=changes&days=30&limit=${CHANGES}`));
  return value ? <ListBody data={changesWidget(value.rows, users)} rows={rows} /> : <Waiting error={error} />;
}
