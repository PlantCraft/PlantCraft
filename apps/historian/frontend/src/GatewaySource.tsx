import { Plus, Trash2 } from "lucide-react";
import type { ReactNode } from "react";
import type { SourceIn } from "./api";
import { t } from "./i18n";

/** Sources the gateway (Telegraf) reads and pushes to the collector (collector/gateway.py). */
export const GATEWAY_KINDS = ["mqtt", "modbus", "sql"] as const;
export const isGateway = (kind: string) => (GATEWAY_KINDS as readonly string[]).includes(kind);

/** A Modbus register or coil to read (catalog/gateway.py checks the same). */
export type Register = { name: string; type: string; address: number | string; data_type?: string; byte_order?: string; scale?: number | string };
const REGISTER_TYPES: Record<string, string> = { holding_register: "Holding register", input_register: "Input register", coil: "Coil", discrete_input: "Discrete input" };
// 16-bit words each type takes; FIXED and UFIXED take their byte order's.
const DATA_TYPES: Record<string, number> = {
  INT16: 1, UINT16: 1, INT32: 2, UINT32: 2, INT64: 4, UINT64: 4, "FLOAT16-IEEE": 1, "FLOAT32-IEEE": 2, "FLOAT64-IEEE": 4,
  INT8L: 1, INT8H: 1, UINT8L: 1, UINT8H: 1, FIXED: 0, UFIXED: 0,
};
const BYTE_ORDERS: Record<number, string[]> = { 1: ["AB", "BA"], 2: ["ABCD", "DCBA", "BADC", "CDAB"], 4: ["ABCDEFGH", "HGFEDCBA", "BADCFEHG", "GHEFCDAB"] };
export const SQL_DRIVERS: Record<string, string> = { postgres: "PostgreSQL", mysql: "MySQL / MariaDB", sqlserver: "SQL Server" };

/** The byte orders a register of this type may have. */
export function byteOrders(dataType: string): string[] {
  const words = DATA_TYPES[dataType];
  return words ? BYTE_ORDERS[words] : [...BYTE_ORDERS[1], ...BYTE_ORDERS[2]];
}

const lines = (value: unknown) => (Array.isArray(value) ? value.join("\n") : String(value ?? ""));

/** The fields of an MQTT, Modbus or SQL source in the source form. */
export function GatewayFields({ draft, setDraft, passwordFields }: { draft: SourceIn; setDraft: (draft: SourceIn) => void; passwordFields: ReactNode }) {
  const set = (key: string, value: unknown) => setDraft({ ...draft, options: { ...draft.options, [key]: value } });
  const endpoint = (event: { target: { value: string } }) => setDraft({ ...draft, endpoint: event.target.value });
  if (draft.kind === "mqtt") return <>
    <label>{t("Broker")}<input value={draft.endpoint} onChange={endpoint} placeholder="tcp://broker:1883" /><small>{t("tcp:// or ssl:// (TLS), ws:// or wss://")}</small></label>
    <label className="formula">{t("Topics")}<textarea className="pc-mono" rows={3} value={lines(draft.options.topics)} onChange={(event) => set("topics", event.target.value.split("\n"))} placeholder={"plant/#\nutilities/+/flow"} />
      <small>{t("One per line; + matches one level, # the rest. Each topic becomes a signal (its tag is the topic with dots).")}</small></label>
    <label>{t("Message format")}<select value={String(draft.options.data_format ?? "value")} onChange={(event) => set("data_format", event.target.value)}>
      <option value="value">{t("A number per message")}</option><option value="json">{t("JSON: each number field")}</option></select></label>
    <label>{t("QoS")}<select value={String(draft.options.qos ?? 0)} onChange={(event) => set("qos", Number(event.target.value))}>
      {[0, 1, 2].map((qos) => <option key={qos} value={qos}>{qos}</option>)}</select><small>{t("1 or 2 keeps messages sent while the gateway restarts.")}</small></label>
    {passwordFields}
  </>;
  if (draft.kind === "modbus") return <>
    <label>{t("Device")}<input value={draft.endpoint} onChange={endpoint} placeholder="tcp://10.0.0.5:502" /><small>{t("Modbus TCP: tcp://host:502")}</small></label>
    <label>{t("Slave id")}<input type="number" min="0" max="255" value={String(draft.options.slave_id ?? 1)} onChange={(event) => set("slave_id", Number(event.target.value))} /></label>
    <label>{t("Timeout (s)")}<input type="number" min="0.1" step="0.1" value={String(draft.options.timeout_seconds ?? 5)} onChange={(event) => set("timeout_seconds", Number(event.target.value))} /></label>
    <Registers registers={(draft.options.registers as Register[] | undefined) ?? []} onChange={(registers) => set("registers", registers)} />
  </>;
  return <>
    <label>{t("Database")}<select value={String(draft.options.driver ?? "postgres")} onChange={(event) => set("driver", event.target.value)}>
      {Object.entries(SQL_DRIVERS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
    <label className="formula">{t("Connection string (DSN)")}<input className="pc-mono" value={draft.endpoint} onChange={endpoint} placeholder="postgres://reader:{password}@lims:5432/lab" />
      <small>{t("Write {password} where the password goes: it is stored encrypted below. Use a database user that can only read.")}</small></label>
    <label className="formula">{t("Query")}<textarea className="pc-mono" rows={4} value={String(draft.options.query ?? "")} onChange={(event) => set("query", event.target.value)} placeholder="SELECT sample_time, tag, result FROM results WHERE sample_time > now() - interval '1 hour'" />
      <small>{t("One SELECT, run every scan period. Each number column becomes a value; a tag column splits rows into signals.")}</small></label>
    <label>{t("Time column (optional)")}<input className="pc-mono" value={String(draft.options.time_column ?? "")} onChange={(event) => set("time_column", event.target.value)} /><small>{t("Empty: the time the query ran.")}</small></label>
    <label>{t("Tag columns (optional)")}<input className="pc-mono" value={lines(draft.options.tag_columns).replace(/\n/g, ", ")} onChange={(event) => set("tag_columns", event.target.value.split(","))} /><small>{t("Comma separated, e.g. tag")}</small></label>
    <label>{t("Measurement")}<input className="pc-mono" value={String(draft.options.measurement ?? "sql")} onChange={(event) => set("measurement", event.target.value)} /></label>
    {passwordFields}
  </>;
}

/** The registers and coils a Modbus source reads: one row each. */
function Registers({ registers, onChange }: { registers: Register[]; onChange: (registers: Register[]) => void }) {
  const update = (index: number, change: Partial<Register>) => onChange(registers.map((item, at) => (at === index ? { ...item, ...change } : item)));
  return <div className="formula registers">
    <span className="registers-title">{t("Registers and coils")}</span>
    <table className="table compact">
      <thead><tr><th>{t("Name")}</th><th>{t("Type")}</th><th>{t("Address")}</th><th>{t("Data type")}</th><th>{t("Byte order")}</th><th>{t("Scale")}</th><th><span className="sr-only">{t("Actions")}</span></th></tr></thead>
      <tbody>{registers.map((item, index) => {
        const word = item.type === "holding_register" || item.type === "input_register";
        const dataType = item.data_type ?? "INT16";
        return <tr key={index}>
          <td><input aria-label={t("Name")} value={item.name} onChange={(event) => update(index, { name: event.target.value })} placeholder="FT-101" /></td>
          <td><select aria-label={t("Type")} value={item.type} onChange={(event) => update(index, { type: event.target.value })}>{Object.entries(REGISTER_TYPES).map(([key, label]) => <option key={key} value={key}>{t(label)}</option>)}</select></td>
          <td><input aria-label={t("Address")} type="number" min="0" max="65535" value={String(item.address)} onChange={(event) => update(index, { address: event.target.value })} /></td>
          <td>{word && <select aria-label={t("Data type")} value={dataType} onChange={(event) => update(index, { data_type: event.target.value, byte_order: byteOrders(event.target.value)[0] })}>{Object.keys(DATA_TYPES).map((key) => <option key={key} value={key}>{key}</option>)}</select>}</td>
          <td>{word && <select aria-label={t("Byte order")} value={item.byte_order ?? byteOrders(dataType)[0]} onChange={(event) => update(index, { byte_order: event.target.value })}>{byteOrders(dataType).map((key) => <option key={key} value={key}>{key}</option>)}</select>}</td>
          <td>{word && <input aria-label={t("Scale")} type="number" step="any" value={String(item.scale ?? 1)} onChange={(event) => update(index, { scale: event.target.value })} />}</td>
          <td><button type="button" className="icon-button danger" aria-label={t("Remove")} onClick={() => onChange(registers.filter((_, at) => at !== index))}><Trash2 size={15} /></button></td>
        </tr>;
      })}</tbody>
    </table>
    <button type="button" className="button button-secondary" onClick={() => onChange([...registers, { name: "", type: "holding_register", address: registers.length, data_type: "INT16", byte_order: "AB", scale: 1 }])}><Plus size={15} />{t("Add register")}</button>
    <small>{t("Addresses start at 0. A 32-bit value takes two registers from its address, a 64-bit one four.")}</small>
  </div>;
}
