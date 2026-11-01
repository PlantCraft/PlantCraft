/** Interface text. English is the source text and the catalog key; this app's translations
 * are locales/<code>.json, over the shared components' own (@plantcraft/ui, docs/translations.md).
 * The language is the one chosen for the whole suite, English while translations are off. */
import { createI18n } from "@plantcraft/ui";
import es from "./locales/es.json";
import ptBR from "./locales/pt-BR.json";

const i18n = createI18n({ "pt-BR": ptBR as Record<string, string>, es: es as Record<string, string> });

/** BCP 47 locale for Intl and localeCompare. */
export const locale = i18n.locale;

/** `text` (English) in the page's language, with `{name}` fields filled in. */
export const t = i18n.t;

/** Numbers, dates and durations as the whole suite writes them. */
export { formatAgo, formatDate, formatDuration, formatNumber, formatShare } from "@plantcraft/ui";
