/** Client-side navigation under the base path the app is served from (`/alarm/`): the suite's
 * own (@plantcraft/ui `createNav`), set to this app's base path. */
import { createNav } from "@plantcraft/ui";
import { useEffect, useMemo, useState } from "react";

export const { BASE, href, appPath, navigate, follow, usePath, Link } = createNav(import.meta.env?.BASE_URL ?? "/");

/** The query of the current page (``?rule=…``), updated on navigation like ``usePath``. */
export function useSearch(): URLSearchParams {
  const [search, setSearch] = useState(() => window.location.search);
  useEffect(() => {
    const update = () => setSearch(window.location.search);
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);
  return useMemo(() => new URLSearchParams(search), [search]);
}
