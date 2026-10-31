/** AI assistant access: the read-only MCP server's switch (Setup, admins) and each person's access
 * tokens (their profile). A token is shown once, with how to connect an assistant to it. */
import { DataTable, FormSection, Heading, confirmAction } from "@plantcraft/ui";
import { AlertTriangle, Ban, Bot, Copy, KeyRound, LoaderCircle, Plus, Power } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { requestJson } from "./api";
import { locale, t } from "./i18n";
import { navigate } from "./nav";

export interface AssistantToken { token_id: string; username: string; label: string; created_at: string; expires_at: string; revoked_at: string | null; last_used_at: string | null; active: boolean; expired: boolean }
export interface AssistantSettings { allowed: boolean; enabled: boolean; max_days: number; endpoint: string; tokens: AssistantToken[] }
export interface MyAssistantAccess { enabled: boolean; max_days: number; can_create: boolean; endpoint: string; tokens: AssistantToken[] }
type NewToken = AssistantToken & { token: string };

const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });

export const assistantApi = {
  settings: () => requestJson<AssistantSettings>("/api/assistant-access"),
  save: (enabled: boolean, maxDays: number) => requestJson<AssistantSettings>("/api/assistant-access", json("PUT", { enabled, max_days: maxDays })),
  revokeAny: (tokenId: string) => requestJson<AssistantToken>(`/api/assistant-access/tokens/${encodeURIComponent(tokenId)}`, json("DELETE")),
  mine: () => requestJson<MyAssistantAccess>("/api/assistant-access/mine"),
  create: (label: string, days?: number) => requestJson<NewToken>("/api/assistant-access/mine", json("POST", { label, days })),
  revoke: (tokenId: string) => requestJson<AssistantToken>(`/api/assistant-access/mine/${encodeURIComponent(tokenId)}`, json("DELETE")),
};

/** The command and the JSON an assistant needs to connect with ``token``. */
export function connectSnippets(endpoint: string, token: string): { label: string; text: string }[] {
  return [
    { label: t("Claude Code"), text: `claude mcp add --transport http plantcraft ${endpoint} --header "Authorization: Bearer ${token}"` },
    { label: t("Other MCP clients (JSON)"), text: JSON.stringify({ mcpServers: { plantcraft: { type: "http", url: endpoint, headers: { Authorization: `Bearer ${token}` } } } }, null, 2) },
  ];
}

function message(error: unknown) {
  return error instanceof Error ? error.message : t("Couldn't complete the operation.");
}

function when(value: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(locale, { day: "2-digit", month: "short", year: "numeric" }).format(date);
}

function state(token: AssistantToken) {
  if (token.revoked_at) return t("Revoked {date}", { date: when(token.revoked_at) });
  if (token.expired) return t("Expired");
  return t("Active until {date}", { date: when(token.expires_at) });
}

async function copy(text: string) {
  try { await navigator.clipboard.writeText(text); return true; } catch { return false; }
}

/** Setup › AI assistant access (administrators). */
export default function AssistantAccessPage() {
  const [data, setData] = useState<AssistantSettings | null>(null);
  const [days, setDays] = useState(30);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => assistantApi.settings().then((value) => { setData(value); setDays(value.max_days); }).catch((err) => setError(message(err))), []);
  useEffect(() => { void load(); }, [load]);

  async function save(enabled: boolean) {
    setBusy(true);
    setError("");
    try { await assistantApi.save(enabled, days); await load(); } catch (err) { setError(message(err)); }
    setBusy(false);
  }
  async function revoke(token: AssistantToken) {
    if (!(await confirmAction(t("Revoke the token {label} of {person}? Their assistant stops reading at once.", { label: token.label || token.token_id, person: token.username }), { confirm: t("Revoke"), danger: true }))) return;
    try { await assistantApi.revokeAny(token.token_id); await load(); } catch (err) { setError(message(err)); }
  }

  return <>
    <Heading eyebrow={<><Bot size={14} /> {t("Administration")} · <a href="/setup" onClick={(event) => { event.preventDefault(); navigate("/setup"); }}>{t("Settings")}</a></>} title={t("AI assistant access (MCP)")}
      detail={t("Lets people connect their own AI assistant (Claude or any client that speaks the Model Context Protocol) to read the plant as they see it: assets, signals and their history, alarms and the apps' results. Read-only: an assistant never changes anything. Off by default.")}
      actions={data && <button type="button" className={`button ${data.enabled ? "button-secondary" : "button-primary"}`} disabled={busy || !data.allowed} onClick={() => void save(!data.enabled)}>{busy ? <LoaderCircle className="spin" /> : <Power />} {data.enabled ? t("Turn off") : t("Turn on")}</button>} />
    {error && <div className="form-error"><AlertTriangle size={15} /> {error}</div>}
    {!data && !error && <div className="module-state"><LoaderCircle className="spin" /></div>}
    {data && <section className="panel form-panel">
      <FormSection id="mcp-state" title={<>{data.enabled ? t("On") : t("Off")}</>} detail={!data.allowed ? t("This installation turned it off for good (PLANTCRAFT_MCP=off). Ask whoever installed it.")
          : data.enabled ? t("People create a token on their profile page and give it to their assistant. Each token reads as its owner, with their access, and stops when it expires, when it is revoked, when its owner loses access or when this is turned off.")
            : t("Turn it on only if your IT agrees that people may use AI assistants with plant data. The assistant runs where each person runs it: a token lets it read what that person reads.")}>
        <form className="form-grid" onSubmit={(event: FormEvent) => { event.preventDefault(); void save(data.enabled); }}>
          <label className="field-span">{t("Address for the assistants")}<input readOnly value={data.endpoint} className="cl-mono" onFocus={(event) => event.target.select()} /></label>
          <label>{t("A token lasts at most (days)")}<input type="number" min={1} max={365} value={days} onChange={(event) => setDays(Number(event.target.value) || 1)} /></label>
          {data.enabled && <div className="field-span"><button type="submit" className="button button-primary" disabled={busy}>{t("Save")}</button></div>}
        </form>
      </FormSection>
      <FormSection id="mcp-tokens" title={t("Access tokens")} detail={t("Every token people created, active or not. Revoking one stops its assistant at once.")}>
      {data.tokens.length === 0 ? <p className="muted">{t("No tokens yet.")}</p>
        : <DataTable rows={data.tokens} rowKey={(token) => token.token_id} label={t("Access tokens")} rowClassName={(token) => (token.active ? undefined : "ac-inactive")} initialSort={{ key: "created", descending: true }}
          columns={[
            { key: "person", label: t("Person"), sort: (token) => token.username, filter: { value: (token) => token.username }, render: (token) => <button type="button" className="as-link-button" onClick={() => navigate(`/people/${encodeURIComponent(token.username)}`)}>{token.username}</button> },
            { key: "label", label: t("Label"), sort: (token) => token.label, render: (token) => token.label || "—" },
            { key: "token", label: t("Token"), render: (token) => <code>pcat_{token.token_id}…</code> },
            { key: "created", label: t("Created"), sort: (token) => token.created_at, render: (token) => when(token.created_at) },
            { key: "used", label: t("Last used"), sort: (token) => token.last_used_at, render: (token) => when(token.last_used_at) },
            { key: "status", label: t("Status"), sort: (token) => (token.active ? 0 : 1), filter: { value: (token) => (token.active ? t("Active") : t("Not active")) }, render: state },
            { key: "actions", label: <span className="sr-only">{t("Actions")}</span>, className: "ac-row-actions", render: (token) => token.active && <button type="button" className="button button-ghost button-icon" title={t("Revoke")} aria-label={t("Revoke token {token}", { token: token.token_id })} onClick={() => void revoke(token)}><Ban /></button> },
          ]} />}
      </FormSection>
    </section>}
  </>;
}

/** My profile › AI assistant: create and revoke my own tokens. */
export function MyAssistantTokens() {
  const [data, setData] = useState<MyAssistantAccess | null>(null);
  const [label, setLabel] = useState("");
  const [created, setCreated] = useState<NewToken | null>(null);
  const [copied, setCopied] = useState("");
  const [error, setError] = useState("");
  const load = useCallback(() => assistantApi.mine().then(setData).catch(() => setData(null)), []);
  useEffect(() => { void load(); }, [load]);
  if (!data || (!data.enabled && data.tokens.length === 0)) return null;

  async function create(event: FormEvent) {
    event.preventDefault();
    setError("");
    try { setCreated(await assistantApi.create(label.trim())); setLabel(""); await load(); } catch (err) { setError(message(err)); }
  }
  async function revoke(token: AssistantToken) {
    if (!(await confirmAction(t("Revoke {label}? The assistant using it stops reading at once.", { label: token.label || token.token_id }), { confirm: t("Revoke"), danger: true }))) return;
    try { await assistantApi.revoke(token.token_id); if (created?.token_id === token.token_id) setCreated(null); await load(); } catch (err) { setError(message(err)); }
  }

  return <div className="pp-notify">
    <h2 className="section-title"><Bot size={15} /> {t("AI assistant")}</h2>
    <p className="muted">{t("Connect your own AI assistant to read the plant as you see it, read-only. Create a token, give it to the assistant, and revoke it when you stop. A token lasts at most {days} days.", { days: data.max_days })}</p>
    {error && <div className="form-error"><AlertTriangle size={15} /> {error}</div>}
    {created && <div className="ac-notice ac-key-reveal">
      <KeyRound size={15} />
      <span>
        <strong>{t("Copy it now: it will not be shown again.")}</strong><code>{created.token}</code>
        {connectSnippets(data.endpoint, created.token).map((snippet) => <span key={snippet.label}><small>{snippet.label}</small><code>{snippet.text}</code>
          <button type="button" className="button button-secondary button-small" onClick={() => void copy(snippet.text).then((ok) => setCopied(ok ? snippet.label : ""))}><Copy size={13} /> {copied === snippet.label ? t("Copied") : t("Copy")}</button></span>)}
      </span>
    </div>}
    {data.can_create && <form className="pp-token-form" onSubmit={create}>
      <input value={label} maxLength={120} placeholder={t("E.g. Claude on my laptop")} aria-label={t("Label")} onChange={(event) => setLabel(event.target.value)} />
      <button className="button button-secondary button-small"><Plus size={14} /> {t("Create token")}</button>
    </form>}
    {data.tokens.length > 0 && <ul className="pp-apps">{data.tokens.map((token) => <li key={token.token_id}>
      <span><code>pcat_{token.token_id}…</code> {token.label}</span>
      <span className="muted">{state(token)}{token.active && <button type="button" className="icon-button" title={t("Revoke")} aria-label={t("Revoke token {token}", { token: token.token_id })} onClick={() => void revoke(token)}><Ban size={14} /></button>}</span>
    </li>)}</ul>}
  </div>;
}
