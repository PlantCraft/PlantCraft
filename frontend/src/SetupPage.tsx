/** Setup (administrators): the settings done once, or seldom, that have no page of their own in
 * the menu. Health, Backups and Updates have their own pages.
 * Only the tiles: the step-by-step path and the intro text are gone. */
import { NextSteps, type JourneyStep } from "@plantcraft/ui";
import { t } from "./i18n";
import { navigate } from "./nav";

/** The Setup tiles, in two groups. Only what has no other place in the menu:
 * sources are the Historian's, asset types are in Assets, people, groups and specialists in Users,
 * apps and app keys in Apps. */
export function setupGroups(): { title: string; items: JourneyStep[] }[] {
  return [
    {
      title: t("Sign-in and audit"),
      items: [
        { title: t("Corporate sign-in"), detail: t("People sign in with their company account (Active Directory, LDAP or single sign-on), and the directory's groups decide their access. Off until you set it up."), to: "/setup/corporate-login" },
        { title: t("Audit log"), detail: t("Who changed what in every app, and every sign-in, failed sign-in and sign-out. Read only, with a CSV for a review."), to: "/setup/audit" },
      ],
    },
    {
      title: t("Settings"),
      items: [
        { title: t("Installation"), detail: t("The installation's time zone: the Local time of every screen and of the schedules saved at local time."), to: "/setup/installation" },
        { title: t("Language models (LLM)"), detail: t("The providers the specialists may use, each with its address, key and models."), to: "/setup/language-model" },
        { title: t("AI assistant access (MCP)"), detail: t("Lets people connect their own AI assistant to read the plant as they see it, read-only, with a token of their own. Off until you turn it on."), to: "/setup/assistant-access" },
        { title: t("Compute"), detail: t("The workers that run the apps' calculations apart from the platform, on this machine or others, and the limits of each app's tasks."), to: "/setup/compute" },
        { title: t("Notebooks"), detail: t("Whether people may analyse the plant's data in Python notebooks, from Desk. Off until you turn it on."), to: "/setup/notebooks" },
        { title: t("Desk"), detail: t("Whether Desk shows the Team page, and whether people may show their Outlook or Google calendar there by its link, and from which servers."), to: "/setup/calendars" },
        { title: t("Email"), detail: t("Your company's mail server, so notifications can also go by email. Optional: they always reach Messages."), to: "/setup/email" },
        { title: t("Apps"), detail: t("What each app lets you set for this installation, and links to its own setup pages."), to: "/setup/apps" },
      ],
    },
  ];
}

export function SetupPage() {
  return <>
    <div className="page-heading"><div><span className="eyebrow">{t("Administration")}</span><h1>{t("Settings")}</h1></div></div>
    {setupGroups().map((group) => <NextSteps key={group.title} title={group.title} navigate={navigate} limit={group.items.length} items={group.items} />)}
  </>;
}
