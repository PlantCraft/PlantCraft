/**
 * The tour's own language, apart from the interface: a first visitor picks it on the tour card
 * (English, Português, Español, Français, Deutsch). It starts from the browser language and is
 * remembered in this browser for every app of the suite. `tt()` translates a tour text: English
 * is the source and the key, the other languages live in tourTexts.ts.
 */
import { useEffect, useState } from "react";
import { translationsOn } from "./i18n.js";
import { TOUR_TEXTS } from "./tourTexts.js";
import { fillText } from "./files.js";

export type TourLanguage = "en" | "pt-BR" | "es" | "fr" | "de";

export const TOUR_LANGUAGES: { code: TourLanguage; label: string }[] = [
  { code: "en", label: "English" },
  { code: "pt-BR", label: "Português (Brasil)" },
  { code: "es", label: "Español" },
  { code: "fr", label: "Français" },
  { code: "de", label: "Deutsch" },
];

export const TOUR_LANGUAGE_KEY = "plantcraft-ui:tour-language";
const CHANGED_EVENT = "plantcraft-ui:tour-language";

/** The tour language for a browser or stored code ("pt", "es-AR", "de-CH"...), or null. */
export function tourLanguageFor(value: string | null | undefined): TourLanguage | null {
  const code = (value ?? "").toLowerCase();
  if (code.startsWith("pt")) return "pt-BR";
  for (const short of ["en", "es", "fr", "de"] as const) if (code.startsWith(short)) return short;
  return null;
}

export function tourLanguage(): TourLanguage {
  if (!translationsOn()) return "en";
  try {
    const stored = tourLanguageFor(window.localStorage.getItem(TOUR_LANGUAGE_KEY));
    if (stored) return stored;
  } catch {
    // Storage blocked: the browser language decides.
  }
  if (typeof navigator !== "undefined") {
    for (const code of navigator.languages ?? [navigator.language]) {
      const found = tourLanguageFor(code);
      if (found) return found;
    }
  }
  return "en";
}

export function setTourLanguage(code: TourLanguage) {
  try {
    window.localStorage.setItem(TOUR_LANGUAGE_KEY, code);
  } catch {
    // Private mode: the choice holds until the page closes.
  }
  window.dispatchEvent(new Event(CHANGED_EVENT));
}

/** A tour text in the tour language; a text with no translation stays in English. */
export function tt(text: string, values?: Record<string, string | number>): string {
  return fillText(TOUR_TEXTS[tourLanguage()]?.[text] ?? text, values);
}

/** The tour language, re-rendering when the person picks another. */
export function useTourLanguage(): TourLanguage {
  const [language, setLanguage] = useState<TourLanguage>(tourLanguage);
  useEffect(() => {
    const changed = () => setLanguage(tourLanguage());
    window.addEventListener(CHANGED_EVENT, changed);
    return () => window.removeEventListener(CHANGED_EVENT, changed);
  }, []);
  return language;
}
