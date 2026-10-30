/** The words of a search marked in a passage, as a search engine shows them:
 * the part of the passage around the first word found, with every word of the search in bold. */
import type { ReactNode } from "react";

// Words too common to mark (English and Portuguese), as the search itself skips them.
const COMMON = new Set([
  "the", "and", "for", "are", "was", "why", "how", "what", "when", "which", "this", "that", "with", "from", "does", "did", "its", "has", "have", "not", "can",
  "que", "por", "para", "com", "uma", "como", "qual", "quando", "onde", "porque", "dos", "das", "nos", "nas", "não", "sao", "são", "está", "esta",
]);

const fold = (text: string) => text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

/** The words of `query` worth marking: three letters or more, or a tag (FIC-1003, FIC 1003). */
export function searchWords(query: string): string[] {
  const words = new Set<string>();
  for (const match of query.matchAll(/[A-Za-z]{1,4}[-_ ]?\d{2,5}[A-Za-z]?/g)) words.add(fold(match[0]).replace(/[-_ ]/, ""));
  for (const word of query.split(/[^\p{L}\p{N}]+/u)) {
    const folded = fold(word);
    if (folded.length >= 3 && !COMMON.has(folded) && !/^\d+$/.test(folded)) words.add(folded);
  }
  return [...words];
}

/** Where each word of `words` is in `text`: [start, end) ranges, in order, not overlapping. */
export function wordRanges(text: string, words: string[]): Array<[number, number]> {
  if (!words.length) return [];
  const folded = fold(text);
  const ranges: Array<[number, number]> = [];
  for (const word of words) {
    // A tag matches with or without its dash or space ("FIC1003" finds "FIC-1003").
    const tag = /^([a-z]{1,4})(\d{2,5}[a-z]?)$/.exec(word);
    const pattern = tag ? new RegExp(`${tag[1]}[-_ ]?${tag[2]}`, "g") : new RegExp(word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g");
    for (const found of folded.matchAll(pattern)) ranges.push([found.index ?? 0, (found.index ?? 0) + found[0].length]);
  }
  ranges.sort((a, b) => a[0] - b[0]);
  const merged: Array<[number, number]> = [];
  for (const range of ranges) {
    const last = merged[merged.length - 1];
    if (last && range[0] <= last[1]) last[1] = Math.max(last[1], range[1]);
    else merged.push([...range]);
  }
  return merged;
}

/** The part of `text` around the first word found, at most `size` characters, cut at spaces. */
export function snippetOf(text: string, words: string[], size = 420): { text: string; start: number } {
  if (text.length <= size) return { text, start: 0 };
  const first = wordRanges(text, words)[0]?.[0] ?? 0;
  let start = Math.max(0, first - Math.round(size / 3));
  if (start > 0) start = text.indexOf(" ", start) + 1 || start;
  let end = Math.min(text.length, start + size);
  if (end < text.length) end = text.lastIndexOf(" ", end) > start ? text.lastIndexOf(" ", end) : end;
  return { text: `${start > 0 ? "…" : ""}${text.slice(start, end)}${end < text.length ? "…" : ""}`, start };
}

/** `text` with the words of `words` in <mark>. */
export function Marked({ text, words }: { text: string; words: string[] }) {
  const ranges = wordRanges(text, words);
  if (!ranges.length) return <>{text}</>;
  const out: ReactNode[] = [];
  let cursor = 0;
  ranges.forEach(([start, end], index) => {
    if (start > cursor) out.push(text.slice(cursor, start));
    out.push(<mark key={index}>{text.slice(start, end)}</mark>);
    cursor = end;
  });
  if (cursor < text.length) out.push(text.slice(cursor));
  return <>{out}</>;
}
