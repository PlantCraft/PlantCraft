import { PageTabs } from "@plantcraft/ui";
import { t } from "./i18n";
import { href, navigate, usePath } from "./nav";

/** Performance | Targets: the alarm load against the ISA-18.2 targets, and the targets. Opened
 * from the Overview; the alarms themselves, each with its history, are in Alarms. */
export function PerformanceTabs() {
  const path = usePath();
  return <PageTabs label={t("Performance")} href={href} navigate={navigate} tabs={[
    { to: "/performance", label: t("Performance"), active: path === "/performance" },
    { to: "/targets", label: t("Targets"), active: path === "/targets" },
  ]} />;
}
