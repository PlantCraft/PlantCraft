/** Each person's Preferences (/api/me/preferences) and Setup › Installation (/api/setup/installation). */
import { setTimeZoneMode, timeZoneMode, TIME_ZONE_MODE_KEY, type TimeZoneMode } from "@plantcraft/ui";
import { requestJson } from "./api";

export interface Preferences { time_zone: TimeZoneMode; language: string | null; installation_time_zone?: string }
export interface InstallationFileEntry { key: string; label: string; value: string }
export interface InstallationFile { present: boolean; path: string; sha256: string | null; entries: InstallationFileEntry[] }
export interface InstallationSettings { time_zone: string; installed_time_zone: string; chosen: boolean; locked?: boolean; installation_file?: InstallationFile; updated_by?: string | null; updated_at?: string | null; now: string }

export const preferencesApi = {
  get: () => requestJson<Preferences>("/api/me/preferences"),
  save: (value: Pick<Preferences, "time_zone" | "language">) => requestJson<Preferences>("/api/me/preferences", { method: "PUT", body: JSON.stringify(value) }),
  installation: () => requestJson<InstallationSettings>("/api/setup/installation"),
  saveInstallation: (time_zone: string) => requestJson<InstallationSettings>("/api/setup/installation", { method: "PUT", body: JSON.stringify({ time_zone }) }),
};

/** What this browser shows until it learns the person's choice: kept in step on sign-in. */
export async function syncPreferences(): Promise<void> {
  try {
    const saved = await preferencesApi.get();
    if (saved.time_zone === timeZoneMode()) return;
    setTimeZoneMode(saved.time_zone, false);
    // Reload once so the times already drawn follow; never in a loop when storage is blocked.
    let kept = false;
    try { kept = window.localStorage.getItem(TIME_ZONE_MODE_KEY) === saved.time_zone; } catch { kept = false; }
    if (kept) window.location.reload();
  } catch {
    // Offline or signed out: this browser's own choice stays.
  }
}

