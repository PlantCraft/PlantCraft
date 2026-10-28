import { SuiteShell, signOut, useSuiteSession } from "@plantcraft/ui";
import { useEffect, useMemo, useState } from "react";
import { api, UNAUTHORIZED_EVENT } from "./api";
import { NotePage, NotesPage } from "./NotesPage";
import { HelpView } from "./SuitePages";
import { t } from "./i18n";
import { href, navigate, usePath } from "./nav";
import { NAV, tourSteps } from "./pages";
import type { Me } from "./types";
import { ErrorBox, Loading } from "./ui";

function Route({ path, me }: { path: string; me: Me }) {
  const [, section, id] = path.split("/").map((part) => decodeURIComponent(part));
  if (section === "notes" && id) return <NotePage key={id} noteId={id} me={me} />;
  if (section === "assets" && id) return <NotesPage key={id} assetId={id} me={me} />;
  if (section === "help") return <HelpView pageId={id || undefined} />;
  if (!section) return <NotesPage me={me} />;
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
  const tour = useMemo(() => (me ? () => tourSteps() : undefined), [me]);
  return <SuiteShell
    app="starter"
    appName="StarterCraft"
    subtitle={t("Example")}
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
