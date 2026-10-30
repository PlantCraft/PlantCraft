/**
 * The one time zone picker of the suite: a list, never a text to type. The
 * person's default comes first ("Local time · Sao Paulo (UTC−3)" or UTC, from their
 * Preferences), then the other of the two, then the fixed offsets UTC−1 … UTC−12 and
 * UTC+1 … UTC+14, and last, folded in its own group, the cities, for zones with daylight saving.
 *
 * It saves "local" for the installation's local time (resolved where it is used, so a schedule
 * follows the installation when its zone changes), "UTC", "Etc/GMT+3" for UTC−3 or a city's
 * IANA name. An unknown saved value stays selectable, as it was written.
 */
import type { ChangeEvent } from "react";
import { t } from "./i18n.js";
import { cityName, cityZones, fixedOffsetZones, isFixedOffset, isUtc, LOCAL_ZONE, offsetLabel, timeZoneLabel, timeZoneMode } from "./timeZone.js";

export interface TimeZoneOption { value: string; label: string }
export interface TimeZoneGroup { label: string | null; options: TimeZoneOption[] }

/** The picker's options in its order; `current` is kept when it is in none of the groups. */
export function timeZoneGroups(current?: string | null, withLocal = true): TimeZoneGroup[] {
  const local = { value: LOCAL_ZONE, label: timeZoneLabel(LOCAL_ZONE, t("Local time")) };
  const utc = { value: "UTC", label: "UTC" };
  const first = !withLocal ? [utc] : timeZoneMode() === "utc" ? [utc, local] : [local, utc];
  const offsets = fixedOffsetZones().map((zone) => ({ value: zone, label: offsetLabel(zone) }));
  const cities = cityZones()
    .map((zone) => ({ value: zone, label: `${cityName(zone)} (${offsetLabel(zone)})`, sort: zone }))
    .sort((a, b) => a.sort.localeCompare(b.sort))
    .map(({ value, label }) => ({ value, label }));
  const groups: TimeZoneGroup[] = [
    { label: null, options: first },
    { label: t("Fixed offsets (no daylight saving)"), options: offsets },
    { label: t("Other city…"), options: cities },
  ];
  const value = (current ?? "").trim();
  const known = !value || (withLocal && value === LOCAL_ZONE) || isUtc(value) || groups.some((group) => group.options.some((option) => option.value === value));
  if (!known) groups[0] = { label: null, options: [...first, { value, label: isFixedOffset(value) ? offsetLabel(value) : value }] };
  return groups;
}

/** A saved value as the picker selects it: nothing is "local", UTC under any name is "UTC". */
export function timeZoneValue(value: string | null | undefined): string {
  const zone = (value ?? "").trim();
  if (!zone) return LOCAL_ZONE;
  return isUtc(zone) ? "UTC" : zone;
}

/** `withLocal={false}` is for choosing the installation's own zone, which "Local time" means. */
export function TimeZoneSelect({ value, onChange, id, name, disabled, ariaLabel = t("Time zone"), withLocal = true }: { value: string | null | undefined; onChange: (zone: string) => void; id?: string; name?: string; disabled?: boolean; ariaLabel?: string; withLocal?: boolean }) {
  const selected = withLocal ? timeZoneValue(value) : timeZoneValue(value) === LOCAL_ZONE ? "UTC" : timeZoneValue(value);
  return (
    <select id={id} name={name} disabled={disabled} aria-label={ariaLabel} className="pc-time-zone" value={selected} onChange={(event: ChangeEvent<HTMLSelectElement>) => onChange(event.target.value)}>
      {timeZoneGroups(selected, withLocal).map((group) => group.label === null
        ? group.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>):
        (
          <optgroup key={group.label} label={group.label}>
            {group.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </optgroup>
        ))}
    </select>
  );
}
