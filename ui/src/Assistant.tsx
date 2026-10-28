/**
 * "Ask the assistant" from outside an app's frame: a link to a new chat about an object in Desk
 * (`/assistant/new?ref=...&q=...`), with the app's questions offered. Inside the suite the
 * assistant opens beside the page (AssistantDrawer.tsx).
 */
import { platformPath } from "./Journey.js";

/** Desk's Assistant: a new chat about ``subject``, the question written in, the app's questions offered. */
export function assistantUrl(platformUrl: string | null | undefined, subject: string, question = "", suggestions: string[] = []): string {
  const query = new URLSearchParams({ ref: subject });
  if (question.trim()) query.set("q", question.trim());
  for (const item of suggestions.slice(0, 6)) query.append("s", item);
  return `${platformPath(platformUrl, "assistant/new")}?${query.toString()}`;
}
