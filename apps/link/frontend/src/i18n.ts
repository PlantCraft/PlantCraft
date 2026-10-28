/** Interface text. English is the only language for now; every string still goes
 * through t() so a catalog can be added later without touching the pages. */
import { fillText } from "@plantcraft/ui";

export const locale = "en-US";

/** `text` with `{name}` fields filled in. */
export const t = fillText;

/** Numbers, dates and durations as the whole suite writes them. */
export { formatAgo, formatDate, formatDuration, formatNumber, formatShare } from "@plantcraft/ui";
