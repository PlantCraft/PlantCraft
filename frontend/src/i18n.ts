import ptBR from "./locales/pt-BR.json";
import { fillText } from "@plantcraft/ui";

/** Interface language. English is the source text and the catalog key; other
 * languages live in locales/<code>.json. Changing language reloads the page. */
export type Language = "en" | "pt-BR";

/** Translations are switched off until the interface settles: everyone sees English and no
 * language picker is shown. Turning them back on is this flag plus the server's
 * PLANTCRAFT_TRANSLATIONS; the catalogs stay in locales/. */
export const TRANSLATIONS = false;

const ALL_LANGUAGES: { code: Language; label: string }[] = [
  { code: "en", label: "English" },
  { code: "pt-BR", label: "Português (Brasil)" },
];

export const LANGUAGES = TRANSLATIONS ? ALL_LANGUAGES : ALL_LANGUAGES.filter((item) => item.code === "en");

const STORAGE_KEY = "processcraft.language";
const COOKIE = "processcraft_language";
const CATALOGS: Partial<Record<Language, Record<string, string>>> = { "pt-BR": ptBR as Record<string, string> };

function supported(value: string | null | undefined): Language | null {
  const code = (value ?? "").toLowerCase();
  if (!code) return null;
  if (code.startsWith("pt")) return "pt-BR";
  if (code.startsWith("en")) return "en";
  return null;
}

function initialLanguage(): Language {
  if (!TRANSLATIONS) return "en";
  try {
    const stored = supported(window.localStorage.getItem(STORAGE_KEY));
    if (stored) return stored;
  } catch {
    // Storage can be blocked; fall back to the browser language.
  }
  if (typeof navigator !== "undefined") return supported(navigator.language) ?? "en";
  return "en";
}

export const language: Language = typeof window === "undefined" ? "en" : initialLanguage();
/** BCP 47 locale for Intl and localeCompare. */
export const locale: string = language === "pt-BR" ? "pt-BR" : "en-US";

if (typeof document !== "undefined") {
  document.documentElement.lang = language;
  // Downloads and links (PDF reports, exports) carry no custom header: the server reads this cookie.
  document.cookie = `${COOKIE}=${language}; path=/; max-age=31536000; SameSite=Lax`;
}

/** `text` (English) in the interface language, with `{name}` fields filled in. */
export function t(text: string, values?: Record<string, string | number>): string {
  const translated = (language === "en" ? text : CATALOGS[language]?.[text]) || text;
  return fillText(translated, values);
}

export function setLanguage(next: Language): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // Without storage the cookie still carries the choice for this browser.
  }
  document.cookie = `${COOKIE}=${next}; path=/; max-age=31536000; SameSite=Lax`;
  window.location.reload();
}
