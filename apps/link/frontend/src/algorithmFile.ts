/**
 * An algorithm as a file (round 9): what it is, what it works on, its diagram,
 * its texts, its data window and its tags, so it moves between sites like a block file. Its
 * assets, owner and versions stay on the site it came from.
 */
import { saveFile } from "@plantcraft/ui";
import type { Diagram } from "@plantcraft/ui/blockEditor";
import { t } from "./i18n";
import { DEFAULT_TIMING, EMPTY_DOCS, type Algorithm, type AlgorithmDocs, type AssetTiming, type SubjectKind } from "./types";

export const ALGORITHM_FORMAT = "plantcraft-algorithm/1";

export type AlgorithmFile = {
  format: typeof ALGORITHM_FORMAT;
  name: string;
  description: string;
  subject_kind: SubjectKind;
  diagram: Diagram;
  docs: AlgorithmDocs;
  timing: AssetTiming;
  tags: string[];
};

const KINDS: SubjectKind[] = ["loop", "signal", "asset"];

export function algorithmFile(algorithm: Algorithm): AlgorithmFile {
  return {
    format: ALGORITHM_FORMAT, name: algorithm.name, description: algorithm.description, subject_kind: algorithm.subject_kind,
    diagram: algorithm.diagram, docs: { ...EMPTY_DOCS, ...algorithm.docs }, timing: algorithm.timing ?? DEFAULT_TIMING, tags: algorithm.tags ?? [],
  };
}

/** Reads a file people chose or pasted; a wrong one says what is wrong instead of throwing later. */
export function parseAlgorithmFile(text: string): AlgorithmFile {
  let raw: unknown;
  try { raw = JSON.parse(text); } catch { throw new Error(t("This is not a JSON file.")); }
  const found = raw as Partial<AlgorithmFile> | null;
  if (!found || typeof found !== "object" || found.format !== ALGORITHM_FORMAT) throw new Error(t("This is not an algorithm file of Analytics ({format}).", { format: ALGORITHM_FORMAT }));
  if (!found.name || typeof found.name !== "string") throw new Error(t("The file has no name."));
  if (!found.subject_kind || !KINDS.includes(found.subject_kind)) throw new Error(t("The file does not say what the algorithm works on."));
  const diagram = found.diagram as Diagram | undefined;
  if (!diagram || !Array.isArray(diagram.nodes) || !Array.isArray(diagram.edges)) throw new Error(t("The file has no diagram."));
  return {
    format: ALGORITHM_FORMAT, name: found.name, description: typeof found.description === "string" ? found.description : "", subject_kind: found.subject_kind,
    diagram, docs: { ...EMPTY_DOCS, ...(found.docs ?? {}) }, timing: { ...DEFAULT_TIMING, ...(found.timing ?? {}) }, tags: Array.isArray(found.tags) ? found.tags.filter((item) => typeof item === "string") : [],
  };
}

export function downloadAlgorithmFile(algorithm: Algorithm): void {
  const name = algorithm.algorithm_id.replace(/[^a-z0-9_-]+/gi, "_");
  saveFile(`${name}.algorithm.json`, JSON.stringify(algorithmFile(algorithm), null, 2), "application/json");
}
