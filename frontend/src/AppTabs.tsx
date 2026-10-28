/** The Apps page's tabs: the installed apps and their keys (administrators). */
import { PageTabs } from "@plantcraft/ui";
import { t } from "./i18n";
import { navigate } from "./nav";

/** Apps and their keys are two tabs of the Apps page: a key always belongs to an app. */
export function AppTabs({ current }: { current: "apps" | "keys" }) {
  return <PageTabs label={t("Apps")} href={(to) => to} navigate={navigate} tabs={[
    { to: "/apps", label: t("Installed apps"), active: current === "apps" },
    { to: "/apps/keys", label: t("App keys"), active: current === "keys" },
  ]} />;
}
