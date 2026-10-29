import { DataTable, type DataColumn } from "@plantcraft/ui";
import { formatDate, t } from "./i18n";
import type { JournalEntry } from "./types";
import { ACTION_WORDS, Link, PRIORITY_WORDS, PriorityPill, reading } from "./ui";

const labelled = (words: Record<string, string>) => Object.entries(words).map(([value, label]) => ({ value, label: t(label) }));

/** Every raise, clear, acknowledgement, shelve and change, newest first. */
export function JournalTable({ rows, showName = true }: { rows: JournalEntry[]; showName?: boolean }) {
  const columns: DataColumn<JournalEntry>[] = [
    { key: "at", label: t("When"), className: "nowrap small", sort: (row) => row.at, render: (row) => formatDate(row.at) },
    ...(showName ? [{ key: "name", label: t("Alarm"), sort: (row: JournalEntry) => row.name, filter: { value: (row: JournalEntry) => row.priority ?? "", options: labelled(PRIORITY_WORDS), label: t("Priority") }, render: (row: JournalEntry) => <><Link to={`/alarms/${row.alarm_id}`}>{row.name}</Link> {row.priority && <PriorityPill priority={row.priority} />}</> }] : []),
    { key: "action", label: t("Event"), className: "strong", sort: (row) => t(ACTION_WORDS[row.action] ?? row.action), filter: { options: labelled(ACTION_WORDS), value: (row) => row.action }, render: (row) => t(ACTION_WORDS[row.action] ?? row.action) },
    { key: "value", label: t("Value"), numeric: true, sort: (row) => (typeof row.value === "number" ? row.value : null), render: (row) => reading(row.value) },
    { key: "by", label: t("By"), phone: "hide", sort: (row) => row.by || t("Alarms"), filter: { value: (row) => row.by || t("Alarms") }, render: (row) => row.by || t("Alarms") },
    { key: "detail", label: t("Detail"), className: "small muted", phone: "hide", render: (row) => row.detail },
  ];
  return <DataTable rows={rows} columns={columns} rowKey={(row) => String(row.id)} initialSort={{ key: "at", descending: true }} label={t("Journal")}
    searchText={(row) => `${row.name} ${row.detail ?? ""} ${row.by ?? ""}`} searchPlaceholder={t("Search alarms or details")} />;
}
