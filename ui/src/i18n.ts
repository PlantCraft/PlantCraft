/** The suite's interface languages, written once for the platform and every app.
 *
 * English is the source text and the catalog key: pages call `t("Save")`. Each module keeps its
 * own catalog file (`locales/pt-BR.json` next to its code) and starts with
 * `createI18n({ "pt-BR": catalog })`; the shared components' own words are in this package's
 * catalog (`ui/src/locales/`) and are merged in, so an app never copies them. A text missing
 * from a catalog shows in English.
 *
 * One choice of language for the whole suite: every app shares PlantCraft's origin, so the
 * choice is kept in a cookie (servers read it too: reports and downloads carry no header) and in
 * this browser's storage. Languages other than English are offered only while the server says
 * translations are on (the `plantcraft_translations` cookie, set by PlantCraft from
 * PLANTCRAFT_TRANSLATIONS); otherwise everyone sees English. */
import { fillText } from "./files.js";
import uiEs from "./locales/es.json" with { type: "json" };
import uiPtBR from "./locales/pt-BR.json" with { type: "json" };

export type Language = "en" | "pt-BR" | "es";
export type Catalog = Record<string, string>;
type Translate = (text: string, values?: Record<string, string | number>) => string;

/** Every language the suite can show, in the order a picker lists them. */
export const SUITE_LANGUAGES: { code: Language; label: string; locale: string }[] = [
  { code: "en", label: "English", locale: "en-US" },
  { code: "pt-BR", label: "Português (Brasil)", locale: "pt-BR" },
  { code: "es", label: "Español", locale: "es" },
];

export const LANGUAGE_COOKIE = "processcraft_language";
export const LANGUAGE_STORAGE_KEY = "processcraft.language";
export const TRANSLATIONS_COOKIE = "plantcraft_translations";

const UI_CATALOGS: Partial<Record<Language, Catalog>> = { "pt-BR": uiPtBR as Catalog, es: uiEs as Catalog };

let translate: Translate = fillText;
let currentLocale = "en-US";
let translations = false;

/** Whether languages other than English are offered (the tour's picker, the language setting). */
export function translationsOn(): boolean {
  return translations;
}

/** Use a translator (and its BCP 47 locale for numbers and dates) in the shared components. */
export function configureUi(options: { t?: Translate; locale?: string; translations?: boolean }) {
  if (options.translations !== undefined) translations = options.translations;
  if (options.t) translate = options.t;
  if (options.locale) currentLocale = options.locale;
}

export function t(text: string, values?: Record<string, string | number>): string {
  return translate(text, values);
}

/** The locale numbers and dates are written in. */
export function uiLocale(): string {
  return currentLocale;
}

/** A supported language for `value` ("pt", "pt-br", "en-GB"), or null. */
export function supportedLanguage(value: string | null | undefined): Language | null {
  const code = (value ?? "").trim().toLowerCase();
  if (!code) return null;
  for (const item of SUITE_LANGUAGES) {
    if (code === item.code.toLowerCase() || code.split("-")[0] === item.code.split("-")[0].toLowerCase()) return item.code;
  }
  return null;
}

function cookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const found = document.cookie.split(";").map((part) => part.trim()).find((part) => part.startsWith(`${name}=`));
  return found ? decodeURIComponent(found.slice(name.length + 1)) : null;
}

/** Whether the server turned translations on for this installation. */
export function serverTranslationsOn(): boolean {
  return cookie(TRANSLATIONS_COOKIE) === "1";
}

/** The language this browser chose: storage, then the shared cookie, then the browser's own. */
export function chosenLanguage(on = serverTranslationsOn()): Language {
  if (!on) return "en";
  try {
    const stored = supportedLanguage(window.localStorage.getItem(LANGUAGE_STORAGE_KEY));
    if (stored) return stored;
  } catch {
    // Storage can be blocked; the cookie and the browser still say.
  }
  const shared = supportedLanguage(cookie(LANGUAGE_COOKIE));
  if (shared) return shared;
  if (typeof navigator !== "undefined") return supportedLanguage(navigator.language) ?? "en";
  return "en";
}

function rememberLanguage(language: Language) {
  if (typeof document === "undefined") return;
  document.documentElement.lang = language;
  document.cookie = `${LANGUAGE_COOKIE}=${language}; path=/; max-age=31536000; SameSite=Lax`;
}

/** Change the language of every app of the suite (the page reloads to redraw in it). */
export function setLanguage(next: Language): void {
  try {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, next);
  } catch {
    // Without storage the cookie still carries the choice for this browser.
  }
  rememberLanguage(next);
  window.location.reload();
}

export interface I18n {
  /** The language the page is drawn in. */
  language: Language;
  /** Its BCP 47 locale, for Intl and localeCompare. */
  locale: string;
  /** The languages offered: English only while translations are off. */
  languages: { code: Language; label: string }[];
  /** `text` (English) in the page's language, with `{name}` fields filled in. */
  t: Translate;
}

/** The translator of one module (the platform or an app): its own catalogs over the shared
 * components' ones. Installs itself for the shared components too. */
export function createI18n(catalogs: Partial<Record<Language, Catalog>> = {}, options: { translations?: boolean } = {}): I18n {
  const on = options.translations ?? serverTranslationsOn();
  const language = typeof window === "undefined" ? "en" : chosenLanguage(on);
  const locale = SUITE_LANGUAGES.find((item) => item.code === language)?.locale ?? "en-US";
  const merged: Catalog = language === "en" ? {} : { ...(UI_CATALOGS[language] ?? {}), ...(catalogs[language] ?? {}) };
  const translateText: Translate = (text, values) => fillText(merged[text] || text, values);
  rememberLanguage(language);
  configureUi({ t: translateText, locale, translations: on });
  return {
    language,
    locale,
    languages: on ? SUITE_LANGUAGES.map(({ code, label }) => ({ code, label })) : SUITE_LANGUAGES.filter((item) => item.code === "en"),
    t: translateText,
  };
}
