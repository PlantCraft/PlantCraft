/** Interface text of the shared components. English is the source; an app that
 * translates (PlantCraft, pt-BR) hands its own `t` and locale to configureUi() at start. */
import { fillText } from "./files.js";

type Translate = (text: string, values?: Record<string, string | number>) => string;

let translate: Translate = fillText;
let currentLocale = "en-US";
// Translations are switched off for now: the suite speaks English until the
// platform settles; the catalogs stay and come back with configureUi({ translations: true }).
let translations = false;

/** Whether languages other than English are offered (the tour's picker, an app's catalog). */
export function translationsOn(): boolean {
  return translations;
}

/** Use the app's translator (and its BCP 47 locale for numbers and dates) in the shared components. */
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
