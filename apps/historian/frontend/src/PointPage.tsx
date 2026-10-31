import { periodRange, TIME_WINDOWS, confirmAction, type TimePeriod, useAssistantPage, windowSeconds } from "@plantcraft/ui";
import { Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { ago, formatBytes, formatCount, formatMs, formatValue } from "./format";
import { t } from "./i18n";
import { navigate } from "./nav";
import { compression, effective, override, PROFILE_LABELS, profileOf, rangeNote } from "./levels";
import { kindLabel } from "./kinds";
import { FormulaHelp } from "./CalcPoint";
import { MODE_LABELS, statusLabel } from "./PointsPage";
import { isWritten, type Me, type Point, type PointSetting, type Profile } from "./types";
import { NotebookButton } from "./notebook";
import { PointEdits } from "./PointEdits";
import { PointNotes } from "./PointNotes";
import { PointTrend } from "./PointTrend";
import { RunsTrend } from "./RunsTrend";
import { ErrorBox, FormFooter, FormSection, Heading, Link, Loading, Pill } from "./ui";

/** `<source id>:<tag>` as its two parts (a tag may itself hold colons). */
export function splitSignal(signal: string): { source: string; tag: string } {
  const at = signal.indexOf(":");
  return at > 0 ? { source: signal.slice(0, at), tag: signal.slice(at + 1) } : { source: "", tag: signal };
}

export function PointPage({ signal, me }: { signal: string; me: Me }) {
  const { tag } = splitSignal(signal);
  const [point, setPoint] = useState<Point | null>(null);
  // The period as in Trends: a relative window ("1h") or "fixed" with its from and to.
  const [period, setPeriod] = useState<TimePeriod>({ window: "1h", from: "", to: "" });
  const fixed = period.window === "fixed";
  const range = Math.max(1, periodRange(period).seconds || 0);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState<Record<string, string | boolean>>({});
  const [message, setMessage] = useState("");
  const opened = useRef(false);

  const loadPoint = () => api.point(signal).then((found) => {
    setPoint(found);
    // A point with sparse values (a lab analysis, an import) opens on a window that shows them.
    if (!opened.current) {
      opened.current = true;
      setPeriod((now) => now.window === "1h" ? { ...now, window: windowFor(found.at) } : now);
    }
    // The settings fields hold the point's own values; empty inherits from the source or the general settings.
    const own = (key: PointSetting) => (found.own[key] === null ? "" : String(found.own[key]));
    setDraft((now) => Object.keys(now).length ? now : {
      name: found.name, description: found.description, unit: found.unit, scan_seconds: own("scan_seconds"), deviation: own("deviation"),
      exception: own("exception"), profile: profileOf(found), min_seconds: found.min_seconds ? String(found.min_seconds) : "",
      low: found.low === null ? "" : String(found.low), high: found.high === null ? "" : String(found.high),
      max_seconds: own("max_seconds"), retention_days: own("retention_days"), step: found.step, enabled: found.enabled, mode: found.own_mode, address: found.address,
    });
  }).catch((err: Error) => setError(err.message));

  useEffect(() => {
    void loadPoint();
    const timer = window.setInterval(() => void loadPoint(), 5000);
    return () => window.clearInterval(timer);
  }, [signal]);
  async function save() {
    setError(""); setMessage("");
    const number = (key: string) => override(String(draft[key] ?? ""));
    // The range is sent only when it changed: saving it makes it the person's (D2).
    const low = number("low"), high = number("high");
    const rangePatch = point!.kind === "number" && (low !== point!.low || high !== point!.high) ? { low, high } : {};
    try {
      const updated = await api.updatePoint(signal, {
        name: String(draft.name ?? ""), description: String(draft.description ?? ""), unit: String(draft.unit ?? ""),
        scan_seconds: number("scan_seconds"), max_seconds: number("max_seconds"), retention_days: number("retention_days"),
        // Lines only (PI's CompMin): empty or 0 archives as often as the compression asks.
        ...(point!.kind === "number" && !draft.step ? { min_seconds: number("min_seconds") } : {}),
        // A profile clears the point's own deviation and exception; "custom" keeps them.
        ...(point!.kind === "number" ? (draft.profile === "custom"
          ? { profile: "", deviation: number("deviation"), exception: number("exception") }
          : { profile: String(draft.profile ?? "") as Profile, deviation: null, exception: null }) : {}),
        ...rangePatch,
        step: !!draft.step, enabled: !!draft.enabled,
        mode: (fixedMode(point!) ? "" : String(draft.mode ?? "")) as Point["own_mode"],
        ...(point!.source_kind === "calc" ? { address: String(draft.address ?? "") } : {}),
      });
      setPoint({ ...point!, ...updated });
      setMessage(t("Saved. The collector applies the change within seconds."));
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }
  async function confirmRange() {
    setError(""); setMessage("");
    try {
      const updated = await api.updatePoint(signal, { low: point!.low, high: point!.high });
      setPoint({ ...point!, ...updated });
      setMessage(t("Range confirmed."));
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }
  async function remove() {
    if (!(await confirmAction(t("Remove {tag}? It stops being collected; its history is kept for 30 days and you can restore it from the Signals page.", { tag: signal }), { confirm: t("Remove"), danger: true }))) return;
    try { await api.deletePoints([signal]); navigate("/points"); } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }

  // What the assistant can do on this page (the button at the top opens it).
  // The Historian's works for a point (app.toml: explain its behaviour, check its quality) and two
  // tasks of the page's own.
  useAssistantPage(point && {
    page: "histcraft:point", subject: `signal:${signal}`,
    facts: { status: point.status, source: point.source_id, scan_seconds: point.scan_seconds, archived: point.stored_values, since: point.first ?? "", quality_reported: point.quality_reported }, title: tag, place: t("Historian › {tag}", { tag }),
    context: [`Historian point ${signal}: ${point.description || point.name}${point.unit ? ` (${point.unit})` : ""}.`,
      `Status ${point.status}${point.detail ? ` (${point.detail})` : ""}; source ${point.source_id} (${point.source_kind}), read every ${point.scan_seconds} s; ${point.stored_values} values archived since ${point.first ?? "never"}.`].join("\n"),
  });
  if (!point && error) return <ErrorBox text={error} />;
  if (!point) return <Loading />;
  // Derived signals are written by their app: these pages only show them.
  const derived = isWritten(point.source_kind);
  const canEdit = me.can_edit && !derived;
  const field = (key: string, label: string, help?: string, type = "text") => <label>{t(label)}
    <input type={type} step="any" disabled={!canEdit} value={String(draft[key] ?? "")} onChange={(event) => setDraft({ ...draft, [key]: event.target.value })} />
    {help && <small>{t(help)}</small>}</label>;
  // A setting with three levels: empty inherits; the line under it says what is in effect and from where.
  const setting = (key: PointSetting, label: string, unit: string, help?: string) => <label>{t(label)}
    <input type="number" step="any" min="0" disabled={!canEdit} value={String(draft[key] ?? "")} placeholder={String(point.own[key] === null ? point[key] : "")} onChange={(event) => setDraft({ ...draft, [key]: event.target.value })} />
    <small className="setting-origin">{effective(point[key], t(unit), point.origins[key])}{help ? `. ${t(help)}` : ""}</small></label>;
  return <>
    <div className="breadcrumb"><Link to="/points">{t("Signals")}</Link> / <span className="pc-mono">{signal}</span></div>
    <Heading
      eyebrow={point.source_id}
      title={tag}
      detail={point.description || point.name}
      actions={<>
        <NotebookButton signals={[signal]} start={fixed ? periodRange(period).start : `-${range}s`} end={fixed ? periodRange(period).end : "now"} />
        {me.is_admin && !derived && <button className="button button-danger" onClick={() => void remove()}><Trash2 size={16} />{t("Remove")}</button>}
      </>}
    />
    {message && <div className="notice notice-ok">{message}</div>}
    {error && <ErrorBox text={error} />}
    {/* What the tour's "One signal" step shows: the value, its status, the archive and the trend. */}
    <div data-tour="point-main">
    <div className="pc-grid">
      <div className="panel kpi-card"><span className="pc-overline">{t("Current value")}</span><b className="pc-num">{formatValue(point.value, point.unit)}</b><small>{formatMs(point.at)} ({ago(point.at)})</small><small className="muted">{t("Kind: {kind}", { kind: kindLabel(point.kind) })}</small></div>
      <div className="panel kpi-card"><span className="pc-overline">{t("Status")}</span><Pill status={point.status} label={statusLabel(point)} /><small>{point.detail || (derived ? t("Written by {source} when it has a new value", { source: point.source_id }) : point.source_kind === "calc" ? t("Calculated every {scan} s", { scan: point.scan_seconds }) : readBy(point))}</small>
        {!point.quality_reported && !derived && <small className="muted">{t("This source does not report quality: its values count as good.")}</small>}</div>
      <div className="panel kpi-card"><span className="pc-overline">{t("Archive")}</span><b className="pc-num">{t("{count} values", { count: formatCount(point.stored_values) })}</b><small>{t("{count} in the last 24 h", { count: formatCount(point.stored_day) })}</small><small>{t("{bytes}, since {first}", { bytes: formatBytes(point.stored_bytes), first: formatMs(point.first) })}</small><small>{t("Kept {retention}", { retention: effective(point.retention_days, t("days"), point.origins.retention_days) })}</small></div>
      <div className="panel kpi-card"><span className="pc-overline">{t("Compression")}</span><b className="pc-num">{point.archived ? `${(point.reads / point.archived).toFixed(1)} : 1` : "—"}</b><small>{t("{reads} read, {archived} archived since the collector started", { reads: formatCount(point.reads), archived: formatCount(point.archived) })}</small></div>
    </div>
    {point.kind === "runs" ? <RunsTrend point={point} signal={signal} tag={tag} />
      : <PointTrend point={point} signal={signal} tag={tag} period={period} onPeriod={setPeriod} />}
    </div>
    {point.kind !== "runs" && <PointNotes signal={signal} period={period} me={me} />}
    {point.kind !== "runs" && !derived && point.mode !== "source" && <PointEdits point={point} signal={signal} period={period} me={me} />}
    <div className="panel form-panel">
      <FormSection title={t("Collection and compression")} detail={derived
        ? point.managed_by
          ? t("Written by its app; its retention and compression are set in {where}.", { where: point.managed_by })
          : t("A derived signal is written by its app; change it there.")
        : t("The rebuilt series never strays more than the deviation from a value read. 0 keeps every change.")}>
      <div className="form-grid">
        {point.source_kind === "calc" && <label className="field-span">{t("Formula")}
          <textarea className="pc-mono" rows={2} disabled={!canEdit} value={String(draft.address ?? "")} onChange={(event) => setDraft({ ...draft, address: event.target.value })} />
          <FormulaHelp /></label>}
        <label>{t("Mode")}<select disabled={!canEdit || fixedMode(point)} value={fixedMode(point) ? "" : String(draft.mode ?? "")} onChange={(event) => setDraft({ ...draft, mode: event.target.value })}>
          <option value="">{t("Source default")}</option>
          {!fixedMode(point) && Object.keys(MODE_LABELS).map((key) => <option key={key} value={key}>{t(MODE_LABELS[key])}</option>)}
        </select><small>{fixedMode(point)
          ? t("This signal exists only in the archive.")
          : t("Now: {mode}.", { mode: t(MODE_LABELS[point.mode] ?? point.mode) })}</small></label>
        {field("name", "Name")}
        {field("description", "Description")}
        {field("unit", "Unit")}
        {point.kind === "number" && field("low", "Range low", undefined, "number")}
        {point.kind === "number" && <label>{t("Range high")}
          <input type="number" step="any" disabled={!canEdit} value={String(draft.high ?? "")} onChange={(event) => setDraft({ ...draft, high: event.target.value })} />
          <small>{rangeNote(point.range_origin)}
            {point.range_origin === "suggested" && canEdit && <> <button type="button" className="button button-secondary button-small" onClick={() => void confirmRange()}>{t("Confirm")}</button></>}</small></label>}
        {!PUSHED.has(point.source_kind) && setting("scan_seconds", "Scan period (s)", "s")}
        {point.kind === "number" && !point.step && <label>{t("Compression profile")}
          <select disabled={!canEdit} value={String(draft.profile ?? "")} onChange={(event) => setDraft({ ...draft, profile: event.target.value })}>
            {Object.entries(PROFILE_LABELS).map(([key, label]) => <option key={key} value={key}>{t(label)}</option>)}
          </select><small>{t("Now: {compression}.", { compression: compression(point) })}</small></label>}
        {point.kind === "number" && draft.profile === "custom" && setting("exception", "Exception", point.unit, "In engineering units; empty takes the general share of the span")}
        {point.kind === "number" && draft.profile === "custom" && setting("deviation", "Deviation", point.unit, point.deviation_percent ? t("No range known: {share}. In engineering units", { share: compression(point) }) : "In engineering units")}
        {point.kind === "number" && !draft.step && field("min_seconds", "Shortest interval between archived values (s)", "Empty: none. A faster change is held until then", "number")}
        {setting("max_seconds", "Longest interval between archived values (s)", "s")}
        {setting("retention_days", "Retention (days)", "days")}
        <p className="form-note">{t("Empty fields take the source's value, else the general settings; the most specific wins.")}</p>
        {point.kind === "number" && <label className="check"><input type="checkbox" disabled={!canEdit} checked={!!draft.step} onChange={(event) => setDraft({ ...draft, step: event.target.checked })} />{t("Holds its value until the next one (on/off, setpoints)")}</label>}
        <label className="check"><input type="checkbox" disabled={!canEdit} checked={!!draft.enabled} onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })} />{t("Collect this signal")}</label>
      </div>
      </FormSection>
      {canEdit && <FormFooter><button className="button button-primary" onClick={() => void save()}>{t("Save")}</button></FormFooter>}
    </div>
  </>;
}

/** A CSV file is read where it is, a calculated point only archived: neither picks a mode. */
/** Calculated, CSV, imported and gateway points exist only in the archive (catalog ARCHIVE_ONLY_KINDS). */
const ARCHIVE_ONLY = new Set(["calc", "csv", "import", "mqtt", "modbus", "sql"]);
const fixedMode = (point: Point) => ARCHIVE_ONLY.has(point.source_kind);
/** The shortest window, from an hour up, that holds the point's newest value twice over. */
function windowFor(at: number | null): string {
  const age = at === null ? 0 : (Date.now() - at) / 1000;
  return TIME_WINDOWS.find((window) => windowSeconds(window) >= Math.max(3600, 2 * age)) ?? TIME_WINDOWS[TIME_WINDOWS.length - 1];
}

/** Kinds whose values arrive without a scan of the point: a file checked by its source, a file
 * loaded once, the gateway (its interval is the source's). A point's scan period does not apply. */
const PUSHED = new Set(["csv", "import", "mqtt", "modbus", "sql"]);

function readBy(point: Point): string {
  if (point.source_kind === "import") return t("Loaded once from a CSV file");
  if (point.source_kind === "csv") return t("Archived from the source's CSV files when they are checked");
  if (PUSHED.has(point.source_kind)) return t("Read by the gateway from {address}", { address: point.address });
  return t("Read every {scan} s from {address}", { scan: point.scan_seconds, address: point.address });
}
