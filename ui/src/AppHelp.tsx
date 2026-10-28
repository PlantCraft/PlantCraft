/**
 * An app's Help page: its guides (`/api/help`, the app standard) in the suite's help browser.
 * The address keeps the open guide (`<help path>?doc=<id>`).
 */
import { useCallback, useEffect, useState } from "react";
import { errorMessage, type HelpEntry } from "./api.js";
import { ErrorBox, Heading, Loading } from "./Blocks.js";
import { HelpBrowser, type HelpDoc } from "./HelpBrowser.js";
import { t } from "./i18n.js";

export interface AppHelpProps {
  /** The help index (`api.help()`). */
  index: () => Promise<HelpEntry[]>;
  /** One guide's Markdown (`api.helpPage(id).then((page) => page.markdown)`). */
  page: (id: string) => Promise<string>;
  /** The browser path of the Help page (`href("/help")`). */
  helpHref: string;
  /** The guide to open first, when the address names none. */
  initial?: string;
}

export function AppHelp({ index, page, helpHref, initial }: AppHelpProps) {
  const [docs, setDocs] = useState<HelpDoc[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    index().then((rows) => setDocs(rows.map((row) => ({ id: row.id, title: row.title, category: row.category || undefined }))))
      .catch((err) => setError(errorMessage(err)));
  }, [index]);
  const load = useCallback((id: string) => page(id), [page]);
  if (error) return <ErrorBox text={error} />;
  if (!docs) return <Loading />;
  return <>
    <Heading title={t("Help")} />
    <HelpBrowser
      docs={docs}
      load={load}
      initial={new URLSearchParams(window.location.search).get("doc") ?? initial}
      onOpen={(id) => window.history.replaceState(window.history.state, "", `${helpHref}?doc=${encodeURIComponent(id)}`)}
    />
  </>;
}
