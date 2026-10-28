/** The pages every app of the suite serves the same way: the help pages. */
import { AppHelp } from "@plantcraft/ui";
import { api } from "./api";
import { href } from "./nav";

/** Help: the app's guides (docs/help, served by /api/help) in the suite's help browser. */
export function HelpView({ pageId }: { pageId?: string }) {
  return <AppHelp index={api.help} page={helpMarkdown} helpHref={href("/help")} initial={pageId} />;
}

const helpMarkdown = (id: string) => api.helpPage(id).then((page) => page.markdown);
