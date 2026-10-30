/** Points an admin removed: kept with their archive for a while, restorable, then deleted for good
 * by the collector (removing a point must never wipe history by one click). */
import { DataTable } from "@plantcraft/ui";
import { RotateCcw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, type RetiredPoint } from "./api";
import { t } from "./i18n";
import { formatMs } from "./format";
import { ErrorBox } from "./ui";

const DAY_MS = 86_400_000;

/** "in 12 days", "today" for the day the collector deletes it. */
export function purgeIn(purgeMs: number, now = Date.now()): string {
  const days = Math.ceil((purgeMs - now) / DAY_MS);
  return days <= 0 ? t("today") : days === 1 ? t("in 1 day") : t("in {count} days", { count: days });
}

export function RetiredPoints({ onRestored }: { onRestored?: () => void }) {
  const [rows, setRows] = useState<RetiredPoint[]>([]);
  const [days, setDays] = useState(30);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [purging, setPurging] = useState<RetiredPoint[] | null>(null);
  const [typed, setTyped] = useState("");
  const load = useCallback(() => api.retiredPoints().then((answer) => { setRows(answer.points); setDays(answer.days); }).catch((err: Error) => setError(err.message)), []);
  useEffect(() => { void load(); }, [load]);
  if (!rows.length && !error) return null;

  async function restore(selected: RetiredPoint[], clear: () => void) {
    setError(""); setMessage("");
    try {
      const answer = await api.restorePoints(selected.map((row) => row.id));
      setMessage(t("{count} signals restored with their history.", { count: answer.restored.length }));
      if (answer.refused.length) setError(answer.refused.map((item) => `${item.signal ?? item.id}: ${item.reason}`).join(" · "));
      clear(); await load(); onRestored?.();
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }
  async function purge() {
    if (!purging) return;
    setError(""); setMessage("");
    try {
      const answer = await api.purgePoints(purging.map((row) => row.id), typed);
      setMessage(t("{count} signals and their history deleted for good.", { count: answer.purged }));
      setPurging(null); setTyped(""); await load();
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }

  return <details className="panel retired-points">
    <summary><h2>{t("Removed signals ({count})", { count: rows.length })}</h2></summary>
    <p className="muted">{t("A removed signal is no longer collected, but its history stays here for {days} days in case it was a mistake. Restore brings it back as it was. After that the history is deleted for good.", { days })}</p>
    {message && <div className="notice notice-ok">{message}</div>}
    {error && <ErrorBox text={error} />}
    {purging && <div className="notice notice-warn retired-confirm">
      <label htmlFor="purge-count">{t("This deletes the history of {count} signals for good. Type {count} to confirm.", { count: purging.length })}</label>
      <input id="purge-count" inputMode="numeric" value={typed} onChange={(event) => setTyped(event.target.value)} />
      <button className="button button-danger" disabled={typed.trim() !== String(purging.length)} onClick={() => void purge()}><Trash2 size={15} />{t("Delete for good")}</button>
      <button className="button button-secondary" onClick={() => { setPurging(null); setTyped(""); }}>{t("Cancel")}</button>
    </div>}
    <DataTable rows={rows} rowKey={(row) => String(row.id)} label={t("Removed signals")} selectable initialSort={{ key: "when", descending: true }}
      searchText={(row) => `${row.signal} ${row.name}`} searchPlaceholder={t("Search tag or name")}
      actions={(selected, clear) => <>
        <button className="button button-secondary" onClick={() => void restore(selected, clear)}><RotateCcw size={15} />{t("Restore")}</button>
        <button className="button button-danger" onClick={() => { setPurging(selected); setTyped(""); }}><Trash2 size={15} />{t("Delete for good")}</button>
      </>}
      columns={[
        { key: "tag", label: t("Tag"), sort: (row) => row.signal, render: (row) => <><span className="pc-mono strong">{row.tag}</span><small className="pc-mono">{row.source_id}</small><small>{row.name}</small></> },
        { key: "when", label: t("Removed"), sort: (row) => row.retired_ms, render: (row) => <>{formatMs(row.retired_ms)}<small>{row.retired_by}</small></> },
        { key: "purge", label: t("History deleted"), sort: (row) => row.purge_ms, render: (row) => purgeIn(row.purge_ms) },
      ]} />
  </details>;
}
