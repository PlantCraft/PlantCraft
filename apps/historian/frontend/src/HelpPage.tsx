import { AppHelp } from "@plantcraft/ui";
import { api } from "./api";
import { href } from "./nav";

const helpMarkdown = (id: string) => api.helpPage(id).then((page) => page.markdown);

/** Historian's guides (docs/help, served by /api/help) in the suite's help browser. */
export function HelpPage() {
  return <AppHelp index={api.help} page={helpMarkdown} helpHref={href("/help")} />;
}
