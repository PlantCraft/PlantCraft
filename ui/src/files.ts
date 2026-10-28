/**
 * Text and files the browser makes on its own, written once for every app: `{name}` fields
 * filled in, and a file handed to the person without a round trip to the server.
 */

/** `text` with its `{name}` fields filled from `values`; unknown fields stay as written. */
export function fillText(text: string, values?: Record<string, string | number>): string {
  if (!values) return text;
  return text.replace(/\{(\w+)\}/g, (match, key: string) => (key in values ? String(values[key]) : match));
}

/** Hands `data` to the person as the file `name` (a text is saved with the MIME `type`). */
export function saveFile(name: string, data: Blob | string, type = "text/plain"): void {
  const blob = typeof data === "string" ? new Blob([data], { type }) : data;
  const url = URL.createObjectURL(blob);
  const link = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.append(link);
  link.click();
  link.remove();
  // Some browsers start the download after the click returns: the address lives a while longer.
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
