/** The assistant on Link's object pages: a run, an algorithm (`useAssistantPage` of @plantcraft/ui). */
import { takeAssistantDraft, useAssistantPage } from "@plantcraft/ui";
import { api } from "./api";
import { t } from "./i18n";
import type { Me } from "./types";

/** The suite's reference of one of Link's objects (`run:linkcraft/<id>`, `algorithm:linkcraft/<id>`,
 * `block:linkcraft/<id>`). */
export function linkRef(kind: "run" | "algorithm" | "block", id: string): string {
  return `${kind}:linkcraft/${id}`;
}

// Drafts read this page load, by work: a form may render twice (React's strict mode) and the
// draft is read only once from the session.
const drafts = new Map<string, Record<string, unknown> | null>();

/** The fields the assistant's card handed to this form (Link's works with a form, app.toml): the
 * first of the works named that left a draft (a new block, or one made from another block). */
export function assistantDraft(...works: Array<"new-block" | "block-variant" | "change-block" | "new-algorithm" | "algorithm-variant">): Record<string, unknown> | null {
  for (const work of works) {
    const key = `linkcraft:${work}`;
    if (!drafts.has(key)) drafts.set(key, takeAssistantDraft(key));
    const found = drafts.get(key);
    if (found) return found;
  }
  return null;
}

/** Tells the assistant about the object on this page (it draws nothing; the button at the top opens
 * the panel, with the page's works in app.toml). Link writes what it knows about the object to
 * PlantCraft first. */
export function LinkAssistant({ kind, id, me, title, failed }: { kind: "run" | "algorithm"; id: string; me: Me; title?: string; failed?: boolean }) {
  const ref = linkRef(kind, id);
  useAssistantPage({ subject: ref, title, platformUrl: me.processcraft_url, page: `linkcraft:${kind}`, place: kind === "run" ? t("Analytics › Run {name}", { name: title ?? id }) : t("Analytics › Algorithm {name}", { name: title ?? id }),
    facts: kind === "run" ? { failed: Boolean(failed) } : {}, prepare: () => api.prepareAssistant(ref) });
  return null;
}
