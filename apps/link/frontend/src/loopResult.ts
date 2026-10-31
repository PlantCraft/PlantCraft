/** A loop's result as an action (LACUNAS A19): PlantCraft's action form opened from the loop page
 * with the result written out, its references, and the loop's charts attached as one PNG.
 *
 * The reference `loop_result:<loop id>@<window end>` (declared in app.toml, `[[contributes.refs]]`)
 * opens the loop again from the action. The image travels in this tab's sessionStorage, which
 * PlantCraft's form reads once (PlantCraft `frontend/src/actionPrefill.ts`): every app is served
 * under PlantCraft's host, so the tab's storage is shared and nothing is uploaded until the
 * person saves the action. */
import { methodLabel } from "./labels";
import { t } from "./i18n";
import type { LoopDetail, Me } from "./types";
import { statusLabel } from "./status";

export const ATTACHMENT_PREFIX = "plantcraft.action-attachment.";
const SEPARATOR = "@";

export function resultRef(loopId: string, end: string | null | undefined): string {
  return `loop_result:${loopId}${end ? `${SEPARATOR}${end}` : ""}`;
}

/** `<loop id>@<window end>` back into its parts (the loop id may hold "@" itself). */
export function parseResult(id: string): { loopId: string; end: string | null } {
  const at = id.lastIndexOf(SEPARATOR);
  if (at <= 0 || !/^\d{4}-\d{2}-\d{2}/.test(id.slice(at + 1))) return { loopId: id, end: null };
  return { loopId: id.slice(0, at), end: id.slice(at + 1) };
}

/** The action's description: the result, its window, the likely cause and what to do first. */
export function resultText(detail: LoopDetail, ref: string): string {
  const summary = detail.summary;
  const lines = [
    t("Analytics result on {loop}: {status}, health {health}.", {
      loop: detail.loop.name || detail.loop.loop_id,
      status: statusLabel(summary?.status ?? "pending"),
      health: summary?.health == null ? "—" : summary.health.toFixed(0),
    }),
  ];
  if (detail.source_start && detail.source_end) lines.push(t("Window {start} to {end} (UTC).", { start: detail.source_start, end: detail.source_end }));
  if (summary?.limiting) lines.push(t("Limiting: {method}{finding}", { method: methodLabel(summary.limiting.method_id), finding: summary.limiting.finding ? `: ${summary.limiting.finding}` : "." }));
  const cause = detail.likely_causes?.[0];
  if (cause) lines.push(t("Likely cause: {cause}. First: {action}", { cause: cause.cause, action: cause.action }));
  lines.push(`#${ref}`);
  return lines.join("\n").slice(0, 4000);
}

export function resultTitle(detail: LoopDetail): string {
  const limiting = detail.summary?.limiting;
  return (limiting ? `${detail.loop.loop_id}: ${methodLabel(limiting.method_id)}` : detail.loop.loop_id).slice(0, 200);
}

/** PlantCraft's action form for the result; `attach` names the image left in sessionStorage. */
export function resultActionUrl(me: Me, detail: LoopDetail, attach: string | null): string {
  const ref = resultRef(detail.loop.loop_id, detail.source_end);
  const query = new URLSearchParams({ new: "1", title: resultTitle(detail) });
  if (detail.origin === "processcraft") query.append("ref", `asset:${String(detail.loop.metadata?.asset_id ?? detail.loop.loop_id)}`);
  query.append("ref", ref);
  query.set("text", resultText(detail, ref));
  if (attach) query.set("attach", attach);
  return `${(me.processcraft_url || "/").replace(/\/$/, "")}/actions?${query.toString()}`;
}

type Plotly = { toImage: (node: HTMLElement, options: { format: "png"; width: number; height: number }) => Promise<string> };

/** The charts inside ``container`` as one PNG data URL (each chart under the other), or null. */
export async function chartsImage(container: HTMLElement | null, plotly: Plotly, width = 1000): Promise<string | null> {
  const nodes = Array.from(container?.querySelectorAll<HTMLElement>(".js-plotly-plot") ?? []);
  if (!nodes.length) return null;
  const height = 320;
  const urls = await Promise.all(nodes.map((node) => plotly.toImage(node, { format: "png", width, height })));
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height * urls.length;
  const context = canvas.getContext("2d");
  if (!context) return urls[0];
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  await Promise.all(urls.map((url, index) => new Promise<void>((done) => {
    const image = new Image();
    image.onload = () => { context.drawImage(image, 0, index * height); done(); };
    image.onerror = () => done();
    image.src = url;
  })));
  return canvas.toDataURL("image/png");
}

/** Leaves the image for PlantCraft's form and returns its key (null when storage is off). */
export function leaveAttachment(name: string, data: string, storage: Pick<Storage, "setItem"> | null = safeSession()): string | null {
  if (!storage) return null;
  const key = Math.random().toString(36).slice(2, 12);
  try { storage.setItem(ATTACHMENT_PREFIX + key, JSON.stringify({ name, data })); return key; } catch { return null; }
}

function safeSession(): Storage | null {
  try { return window.sessionStorage; } catch { return null; }
}
