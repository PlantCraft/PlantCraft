import ptBR from "./locales/pt-BR.json";
import { createI18n, setLanguage, type Language } from "@plantcraft/ui";

/** Interface language. English is the source text and the catalog key; PlantCraft's own
 * translations live in locales/<code>.json, the shared components' in @plantcraft/ui
 * (docs/translations.md). Other languages are offered only while the server's
 * PLANTCRAFT_TRANSLATIONS is on; changing language reloads the page. */
const i18n = createI18n({ "pt-BR": ptBR as Record<string, string> });

export type { Language };
export { setLanguage };
export const { t, language, locale } = i18n;
export const LANGUAGES = i18n.languages;
