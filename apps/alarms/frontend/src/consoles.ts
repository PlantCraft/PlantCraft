/** Consoles (operator positions): the pure helpers of Targets and Performance. */
import { t } from "./i18n";
import type { Console, ConsoleLoad } from "./types";

/** A new console's id: console-1, console-2… the first one not taken. */
export function newConsoleId(consoles: Console[]): string {
  const taken = new Set(consoles.map((item) => item.id));
  let n = consoles.length + 1;
  while (taken.has(`console-${n}`)) n += 1;
  return `console-${n}`;
}

/** What keeps the consoles from being saved ("" when nothing). */
export function consolesProblem(consoles: Console[]): string {
  const names = new Set<string>();
  for (const item of consoles) {
    const name = item.name.trim().split(/\s+/).join(" ").toLowerCase();
    if (!name) return t("Every console needs a name.");
    if (names.has(name)) return t("Two consoles are called {name}.", { name: item.name.trim() });
    names.add(name);
    if (!item.areas.length) return t("Console {name} covers no area yet.", { name: item.name.trim() });
  }
  return "";
}

/** The console a person opens Performance on: the one they sit at, else every alarm (""). */
export function homeConsole(loads: ConsoleLoad[], username: string): string {
  return loads.find((item) => item.operators.includes(username))?.id ?? "";
}
