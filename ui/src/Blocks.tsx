/**
 * The building blocks every page of the suite is made of: the page heading, status pills,
 * the loading and error states and the health bar. Their styles are in base.css.
 */
import { AlertTriangle, LoaderCircle } from "lucide-react";
import type { ReactNode } from "react";
import { AssistantTitleButton } from "./AssistantDrawer.js";
import { statusVar } from "./brandTheme.js";
import { t } from "./i18n.js";

/**
 * The top of every page (round 8): the title at the left, the page's buttons at
 * the right, in a band of one height (base.css), so the buttons stay at the same place from page to
 * page. `eyebrow` and `detail` are no longer drawn (the sidebar says where the person is); they stay
 * accepted so older pages build, and are left out of new ones. The assistant's button sits beside
 * the title (round 9); `assistant={false}` leaves it out (a page about the assistant itself).
 */
export function Heading({ title, actions, assistant = true }: { eyebrow?: ReactNode; title: ReactNode; detail?: ReactNode; actions?: ReactNode; assistant?: boolean }) {
  return (
    <div className="page-heading">
      <div className="page-heading-title">
        <h1>{title}</h1>
        {assistant && <AssistantTitleButton />}
      </div>
      {actions && <div className="heading-actions">{actions}</div>}
    </div>
  );
}

/** One block of a long form (base.css, "Forms and dialogs"): the title and what it is for at the
 * left, the fields at the right. `id` names the section for links and tests. */
export function FormSection({ title, detail, icon, id, children }: { title: ReactNode; detail?: ReactNode; icon?: ReactNode; id?: string; children: ReactNode }) {
  return (
    <section className="form-section" id={id} aria-labelledby={id ? `${id}-title` : undefined}>
      <header>
        <h2 id={id ? `${id}-title` : undefined}>{icon}{title}</h2>
        {detail && (typeof detail === "string" ? <p>{detail}</p> : detail)}
      </header>
      <div className="form-section-body">{children}</div>
    </section>
  );
}

/** The end of a form: a note at the left (what saving does), then Cancel and the main action.
 * `sticky` keeps it at the bottom of the screen while a long form scrolls. */
export function FormFooter({ note, sticky, children }: { note?: ReactNode; sticky?: boolean; children: ReactNode }) {
  return (
    <footer className={sticky ? "form-footer form-footer-sticky" : "form-footer"}>
      {note && <span className="form-footer-note">{note}</span>}
      {children}
    </footer>
  );
}

export function Pill({ status, label }: { status: string; label: ReactNode }) {
  return (
    <span className="pill" style={{ color: statusVar(status, "text"), background: statusVar(status, "soft") }}>
      <i style={{ background: statusVar(status) }} />
      {label}
    </span>
  );
}

export function Loading({ text }: { text?: string }) {
  return <div className="module-state"><LoaderCircle className="spin" /><span>{text ?? t("Loading…")}</span></div>;
}

export function ErrorBox({ text }: { text: string }) {
  return <div className="module-state module-error" role="alert"><AlertTriangle /><span>{text}</span></div>;
}

/** Health 0-100 as a bar in the status colours, with the number. */
export function Health({ value }: { value?: number | null }) {
  if (value === null || value === undefined) return <span className="muted">—</span>;
  const tone = value >= 80 ? "normal" : value >= 60 ? "medium" : value >= 40 ? "high" : "critical";
  return (
    <span className="health">
      <span className="health-bar"><span style={{ width: `${Math.max(2, Math.min(100, value))}%`, background: statusVar(tone) }} /></span>
      <b className="pc-num">{Math.round(value)}</b>
    </span>
  );
}
