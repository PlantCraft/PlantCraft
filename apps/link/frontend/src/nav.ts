/** Client-side navigation under the base path the app is served from (`/link/`): the suite's
 * own (@plantcraft/ui `createNav`), set to this app's base path. */
import { createNav } from "@plantcraft/ui";

export const { BASE, href, appPath, navigate, follow, usePath, Link } = createNav(import.meta.env?.BASE_URL ?? "/");

/** A Signal quality run's page is /runs/<this><run id>. */
export const SIGNAL_RUN_PREFIX = "signal-quality-";
