import { HelpBrowser, type HelpDoc } from "@plantcraft/ui";
import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { t } from "./i18n";
import { href } from "./nav";
import { ErrorBox, Heading, Loading } from "./ui";

/** The page a help address opens: `/help?doc=<id>`, or `/help/methods/<id>` (a method's page). */
export function initialDoc(path: string, search: string): string | undefined {
  const method = /^\/help\/methods\/(.+)$/.exec(path);
  if (method) return `methods/${decodeURIComponent(method[1])}`;
  return new URLSearchParams(search).get("doc") ?? undefined;
}

/** Analytics' guides and method pages (served by /api/help/docs) in the suite's help browser. */
export function HelpPage({ path }: { path: string }) {
  const [docs, setDocs] = useState<HelpDoc[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.helpDocs().then((rows) => setDocs(rows.map((row) => ({ id: row.id, title: row.title, category: row.category || undefined }))))
      .catch((err: Error) => setError(err.message));
  }, []);
  const load = useCallback((id: string) => api.helpDoc(id).then((page) => page.markdown), []);
  if (error) return <ErrorBox text={error} />;
  if (!docs) return <Loading />;
  return <>
    <Heading title={t("Help")} />
    <HelpBrowser
      docs={docs}
      load={load}
      initial={initialDoc(path, window.location.search) ?? docs[0]?.id}
      onOpen={(id) => window.history.replaceState(window.history.state, "", `${href("/help")}?doc=${encodeURIComponent(id)}`)}
    />
  </>;
}
