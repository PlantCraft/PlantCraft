/** Client-side navigation under the base path the app is served from (`/doc/`): the suite's
 * own (@plantcraft/ui `createNav`), set to this app's base path. */
import { createNav } from "@plantcraft/ui";

export const { BASE, href, appPath, navigate, follow, usePath, Link } = createNav(import.meta.env?.BASE_URL ?? "/");
