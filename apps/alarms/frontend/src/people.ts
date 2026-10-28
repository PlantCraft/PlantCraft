/** The platform's people and groups (owners and recipients), read once per page load. */
import { recipientLabel } from "@plantcraft/ui";
import { useEffect, useState } from "react";
import { api } from "./api";
import { t } from "./i18n";
import type { Alarm, Directory } from "./types";

const EMPTY: Directory = { people: [], groups: [], disciplines: [], priorities: [] };
let cached: Promise<Directory> | null = null;

export function useDirectory(): Directory {
  const [directory, setDirectory] = useState<Directory>(EMPTY);
  useEffect(() => {
    cached ??= api.directory().catch(() => { cached = null; return EMPTY; });
    let live = true;
    void cached.then((value) => { if (live) setDirectory(value); });
    return () => { live = false; };
  }, []);
  return directory;
}

/** "Ana Lima", "Unit 100 operations (group)", "the alarm's owner" or "–". */
export function whoLabel(ref: string | null | undefined, directory: Directory): string {
  if (!ref) return "–";
  if (ref === "owner") return t("The alarm's owner");
  return recipientLabel(ref, directory.people, directory.groups);
}

export type Scope = "mine" | "all";

/** The alarms of one scope: "mine" keeps those the person owns or is notified about. */
export function inScope(alarms: Alarm[], scope: Scope): Alarm[] {
  return scope === "mine" ? alarms.filter((alarm) => alarm.mine) : alarms;
}
