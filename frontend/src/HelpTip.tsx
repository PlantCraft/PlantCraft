import { HelpCircle } from "lucide-react";
import { t } from "./i18n";

export function HelpTip({ text, label = t("Show help") }: { text: string; label?: string }) {
  return <span className="help-tip"><button type="button" aria-label={label} onClick={(event) => { event.preventDefault(); event.stopPropagation(); }}><HelpCircle /></button><span className="help-tip-content" role="tooltip">{text}</span></span>;
}
