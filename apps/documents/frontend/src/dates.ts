import { locale } from "./i18n";

/** A revision's issue day ("2026-03-02") as that day: not a UTC midnight moved into the plant's
 * zone, which wrote "Mar 2, 2026, 12:00 AM UTC", or Mar 1 west of Greenwich. */
export function issuedDay(value: string, language: string = locale): string {
  const day = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!day) return value;
  const noon = Date.UTC(Number(day[1]), Number(day[2]) - 1, Number(day[3]), 12);
  return new Date(noon).toLocaleDateString(language, { dateStyle: "medium", timeZone: "UTC" });
}
