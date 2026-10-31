/** What an app hands PlantCraft's action form in its address (docs/collaboration.md):
 * `/actions?new=1&title=...&ref=kind:id&text=...&attach=<key>`. `attach` names an image the app
 * left in this tab's sessionStorage (same origin: every app is served under PlantCraft's host),
 * under `plantcraft.action-attachment.<key>` as `{name, data}` with a PNG, JPEG or WebP data URL:
 * the chart of the result the action is opened from (LACUNAS A19). It is read once and removed. */

export type Attachment = { name: string; data: string };
export type Prefill = { title: string; refs: string[]; text: string; attachment: Attachment | null };

export const ATTACHMENT_PREFIX = "plantcraft.action-attachment.";
const IMAGE = /^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+$/;

export function takeAttachment(key: string | null, storage: Pick<Storage, "getItem" | "removeItem"> | null = safeSession()): Attachment | null {
  if (!key || !storage || !/^[A-Za-z0-9_-]{1,64}$/.test(key)) return null;
  try {
    const raw = storage.getItem(ATTACHMENT_PREFIX + key);
    storage.removeItem(ATTACHMENT_PREFIX + key);
    if (!raw) return null;
    const found = JSON.parse(raw) as Partial<Attachment>;
    if (typeof found.data !== "string" || !IMAGE.test(found.data)) return null;
    return { name: typeof found.name === "string" && found.name.trim() ? found.name.trim().slice(0, 120) : "chart.png", data: found.data };
  } catch {
    return null;
  }
}

export function readPrefill(search: string, storage?: Pick<Storage, "getItem" | "removeItem"> | null): Prefill | null {
  const params = new URLSearchParams(search);
  if (!params.get("new")) return null;
  return {
    title: params.get("title") ?? "",
    refs: params.getAll("ref").filter(Boolean),
    text: (params.get("text") ?? "").slice(0, 4000),
    attachment: takeAttachment(params.get("attach"), storage === undefined ? safeSession() : storage),
  };
}

function safeSession(): Storage | null {
  try { return window.sessionStorage; } catch { return null; }
}
