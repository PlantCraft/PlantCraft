import { SuiteShell, signOut, useSuiteSession } from "@plantcraft/ui";
import { useEffect, useMemo, useState } from "react";
import { api, UNAUTHORIZED_EVENT } from "./api";
import { DocumentPage, DocumentView } from "./DocumentPage";
import { LibraryPage } from "./LibraryPage";
import { OverviewPage } from "./OverviewPage";
import { SearchPage } from "./SearchPage";
import { HelpView } from "./SuitePages";
import { t } from "./i18n";
import { href, navigate, usePath } from "./nav";
import { NAV, tourExample, tourSteps } from "./pages";
import type { Me } from "./types";
import { ErrorBox, Loading } from "./ui";

function Route({ path, me }: { path: string; me: Me }) {
  const [, section, id, part] = path.split("/").map((part) => decodeURIComponent(part));
  if (section === "documents" && id && part === "view") return <DocumentView key={`v-${id}`} docId={id} me={me} />;
  if (section === "documents" && id) return <DocumentPage key={id} docId={id} me={me} />;
  if (section === "folders" && id) return <LibraryPage key={`f-${id}`} folderId={id} me={me} />;
  if (section === "assets" && id) return <LibraryPage key={`a-${id}`} assetId={id} me={me} />;
  if (section === "search") return <SearchPage me={me} />;
  // The reading queue moved to the suite's Queue (side bar); an old link opens the library.
  if (section === "queue") return <LibraryPage me={me} />;
  if (section === "help") return <HelpView pageId={id || undefined} />;
  if (section === "documents") return <LibraryPage me={me} />;
  if (!section) return <OverviewPage me={me} />;
  return <ErrorBox text={t("Page not found.")} />;
}

export function App() {
  const path = usePath();
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState("");
  useSuiteSession(UNAUTHORIZED_EVENT);
  useEffect(() => {
    api.me().then(setMe).catch((err: Error) => setError(err.message));
  }, []);
  // The tour opens one document (owner, 2026-10-28): found before it starts.
  const [example, setExample] = useState<string | null | undefined>(undefined);
  useEffect(() => { if (me) void tourExample().then(setExample); }, [me]);
  const tour = useMemo(() => (me && example !== undefined ? () => tourSteps(example) : undefined), [me, example]);
  return <SuiteShell
    app="doccraft"
    appName="PlantCraft Documents"
    subtitle={t("Plant documents")}
    nav={NAV.map((item) => ({ ...item, label: t(item.label) }))}
    path={path}
    href={href}
    navigate={navigate}
    user={me ? { name: me.name, role: t(me.role) } : null}
    onSignOut={() => void signOut()}
    helpTo="/help"
    version={me?.version ?? null}
    tour={tour}
  >
    {error ? <ErrorBox text={error} /> : me ? <Route path={path} me={me} /> : <Loading />}
  </SuiteShell>;
}
