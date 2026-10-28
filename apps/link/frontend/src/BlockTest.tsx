/**
 * Run a block on one asset's window, without saving anything: first the asset, then one row per
 * input with the point of the asset it reads (its role: PV, SP, OP…) or a signal by its id
 * (round 9), and every output is drawn. Works on a saved block and on a draft in the form.
 */
import type { TraceValue } from "@plantcraft/ui/blockEditor";
import { Play } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "./api";
import { blockComparison, CompareView } from "./Compare";
import { assetChoices } from "./AssetSettings";
import { plotTheme } from "@plantcraft/ui";
import { formatDate, t } from "./i18n";
import { Plot } from "@plantcraft/ui/plot";
import { resultLabel } from "./status";
import type { AssetChoice, BlockFileDoc, BlockTestAnswer } from "./types";
import { Pill } from "./ui";

type InputPort = { port: string; label?: string; type: string; types?: string[] };

function TraceView({ value, title }: { value: TraceValue | undefined; title: string }) {
  if (!value || value.type === "none") return <p className="muted small">{t("Nothing.")}</p>;
  if (value.type === "missing") return <p className="muted small">{value.reason}</p>;
  if (value.type === "number") return <p className="blkt-number pc-num">{value.value.toLocaleString(undefined, { maximumFractionDigits: 6 })}</p>;
  if (value.type === "result") {
    return <p className="blkt-result"><Pill status={value.status === "bad" ? "alarm" : value.status} label={resultLabel(value.status)} />{value.value !== null && <b className="pc-num">{Math.round(value.value)}</b>}<span>{value.message}</span></p>;
  }
  const numeric = value.type === "series";
  return <div className="blkt-plot">
    <Plot
      data={[{ x: value.t, y: value.v, type: "scatter", mode: "lines", name: title, line: { width: 1.5, shape: numeric ? "linear" : "hv" } }]}
      layout={{ ...plotTheme(), autosize: true, height: 180, margin: { l: 48, r: 12, t: 8, b: 32 }, showlegend: false }}
      config={{ displaylogo: false, displayModeBar: false, responsive: true }}
      style={{ width: "100%" }}
      useResizeHandler
    />
    <small className="muted">{t("{count} values, last {value}", { count: value.count, value: value.last ?? "—" })}</small>
  </div>;
}

export function BlockTest({ subject, inputs, outputs, parameters = {}, compare }: {
  /** A saved block (`{ block_id }`) or a draft file. */
  subject: BlockFileDoc | { block_id: string };
  /** Versions to run side by side on the same window (the Compare tab, D18), instead of `subject`. */
  compare?: Array<{ label: string; block_id: string }>;
  inputs: InputPort[];
  outputs: Array<{ port: string; label?: string }>;
  parameters?: Record<string, unknown>;
}) {
  const [choices, setChoices] = useState<AssetChoice[]>([]);
  const [assetId, setAssetId] = useState("");
  const [roles, setRoles] = useState<Record<string, string>>({});
  const [signals, setSignals] = useState<Record<string, string>>({});
  const [answer, setAnswer] = useState<BlockTestAnswer | null>(null);
  const [compared, setCompared] = useState<BlockTestAnswer[] | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { assetChoices().then((found) => { setChoices(found); setAssetId((now) => now || found.find((item) => item.roles.length)?.id || ""); }).catch(() => setChoices([])); }, []);
  const asset = choices.find((item) => item.id === assetId);
  const readable = inputs.filter((port) => ["series", "state"].includes(port.type) || (port.types ?? []).some((item) => item === "series" || item === "state"));
  const others = inputs.filter((port) => !readable.includes(port));
  useEffect(() => {
    if (!asset) return;
    setRoles((now) => Object.fromEntries(readable.map((port, index) => [port.port, now[port.port] && asset.roles.includes(now[port.port]) ? now[port.port] : asset.roles.includes(port.port) ? port.port : asset.roles[Math.min(index, asset.roles.length - 1)] ?? ""])));
    // Roles follow the asset chosen.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assetId, choices.length]);
  async function run() {
    setRunning(true);
    setError("");
    try {
      if (compare?.length) {
        // The first run fixes the window; the others read the same data.
        const first = await api.testBlock({ block_id: compare[0].block_id }, assetId, roles, signals, parameters);
        const end = first.window?.end;
        const rest = await Promise.all(compare.slice(1).map((item) => api.testBlock({ block_id: item.block_id }, assetId, roles, signals, parameters, end)));
        setCompared([first, ...rest]);
      } else setAnswer(await api.testBlock(subject, assetId, roles, signals, parameters));
    }
    catch (err) { setAnswer(null); setCompared(null); setError(err instanceof Error ? err.message : String(err)); }
    finally { setRunning(false); }
  }
  return <section className="panel blkt" aria-label={t("Test")}>
    <div className="panel-header"><div>{compare
      ? <><h2>{t("Compare on an asset")}</h2><p>{t("Runs {versions} on the same window of the asset, their inputs read from its signals. Nothing is saved.", { versions: compare.map((item) => item.label).join(", ") })}</p></>
      : <><h2>{t("Test on an asset")}</h2><p>{t("Runs the block on the asset's last window, its inputs read from the asset's signals. Nothing is saved.")}</p></>}</div></div>
    <div className="blkt-step">
      <h3><span className="blkf-part-number pc-num" aria-hidden="true">1</span>{t("The asset")}</h3>
      <select id="blkt-asset" aria-label={t("Asset")} value={assetId} onChange={(event) => setAssetId(event.target.value)}>
        {!assetId && <option value="">{t("Choose an asset…")}</option>}
        {choices.map((item) => <option key={item.id} value={item.id}>{item.path ? `${item.name} · ${item.path}` : item.name}</option>)}
      </select>
    </div>
    {readable.length > 0 && <div className="blkt-step">
      <h3><span className="blkf-part-number pc-num" aria-hidden="true">2</span>{t("What each input reads")}</h3>
      <p className="muted small">{t("Each input reads one signal of the asset, by its role (PV, SP, OP…), or a signal by its id.")}</p>
      <div className="blk-table-wrap"><table className="table blkt-points">
        <thead><tr><th>{t("Input")}</th><th>{t("Signal of the asset")}</th><th>{t("Or a signal id")}</th></tr></thead>
        <tbody>{readable.map((port) => <tr key={port.port}>
          <td><b>{port.label || port.port}</b><small className="muted"> {port.port}</small></td>
          <td><select aria-label={t("Role for {port}", { port: port.port })} value={roles[port.port] ?? ""} onChange={(event) => setRoles({ ...roles, [port.port]: event.target.value })}>
            <option value="">{t("not wired")}</option>
            {(asset?.roles ?? []).map((role) => <option key={role} value={role}>{role}</option>)}
          </select></td>
          <td><input aria-label={t("Signal id for {port}", { port: port.port })} placeholder={t("optional")} value={signals[port.port] ?? ""} onChange={(event) => setSignals({ ...signals, [port.port]: event.target.value })} /></td>
        </tr>)}</tbody>
      </table></div>
    </div>}
    {others.length > 0 && <p className="muted small">{t("Inputs of other types ({ports}) are left unwired here; test them inside an algorithm.", { ports: others.map((port) => port.port).join(", ") })}</p>}
    <div className="row-actions blkt-run"><button type="button" className="button button-primary" disabled={running || !assetId} onClick={() => void run()}><Play size={16} />{running ? t("Running…") : compare ? t("Run and compare") : t("Run the test")}</button></div>
    {error && <div className="notice notice-error" role="alert">{error}</div>}
    {answer && !answer.check.valid && <div className="notice notice-error" role="alert">{answer.check.errors.join(" ")}</div>}
    {compared && <CompareView columns={compare?.map((item) => item.label) ?? []} subject={compared[0].asset_name ?? compared[0].asset_id}
      window={compared[0].window} comparison={blockComparison(compared, Object.fromEntries([...inputs, ...outputs].map((port) => [port.port, port.label || port.port])))} />}
    {answer?.outputs && <div className="blkt-answer">
      <p className="muted small">{t("{asset}, {start} to {end}", { asset: answer.asset_name ?? answer.asset_id ?? "", start: formatDate(answer.window?.start), end: formatDate(answer.window?.end) })}</p>
      <div className="pc-grid pc-grid-2">
        {outputs.map((port) => <div key={port.port} className="blkt-port"><h3>{t("Output")}: {port.label || port.port}</h3><TraceView value={answer.outputs?.[port.port]} title={port.port} /></div>)}
        {readable.filter((port) => answer.inputs?.[port.port]).map((port) => <div key={port.port} className="blkt-port"><h3>{t("Input")}: {port.label || port.port}</h3><TraceView value={answer.inputs?.[port.port]} title={port.port} /></div>)}
      </div>
    </div>}
  </section>;
}
