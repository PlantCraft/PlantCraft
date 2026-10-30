/**
 * An object's versions in a tab of their own (round 9): Link's blocks and
 * algorithms, Models' blocks and models. On top, what the object is ("About": who owns it, its
 * tags, who made it), then every version, newest first, each with its name, what changed, who
 * saved it and when. Opening a version shows it in the other tabs (the page decides how).
 * Styles in base.css ("Versions").
 */
import { Lock } from "lucide-react";
import type { ReactNode } from "react";
import { formatDate } from "./format.js";
import { t } from "./i18n.js";

/** In place of New version on an object that cannot get one (a block PlantCraft ships): a
 * closed lock and why. */
export function VersionLock({ children }: { children: ReactNode }) {
  return <span className="pc-version-lock" role="note"><Lock size={15} aria-hidden="true" />{children}</span>;
}

export type VersionItem = {
  number: number;
  /** A short name: "Wider window". */
  name?: string | null;
  /** What changed in it, in the saver's words. */
  description?: string | null;
  author?: string | null;
  /** When it was saved (ISO); `note` instead when there is no date ("ships with Link 0.4.0"). */
  at?: string | null;
  note?: string | null;
  current?: boolean;
};

export function VersionsTab({ about, versions, shown, onOpen, footer, label, actions }: {
  /** The object's "About" (owner, tags, maker), drawn above the list. */
  about?: ReactNode;
  versions: VersionItem[] | null;
  /** The version the page shows now. */
  shown?: number;
  /** Open a version (the page shows it in its other tabs); without it the list is read-only. */
  onOpen?: (number: number) => void;
  /** A line under the list (how saving works for this kind of object). */
  footer?: ReactNode;
  label?: string;
  /** Beside the list's title: New version, or why there is none (a lock). */
  actions?: ReactNode;
}) {
  return <div className="pc-versions-tab">
    {about}
    <section className="panel pc-versions" aria-label={label ?? t("Versions")}>
      <div className="panel-header"><div><h2>{label ?? t("Versions")}</h2><p>{t("Newest first. Saving a change makes a new version; the older ones stay to read and compare.")}</p></div>{actions && <div className="row-actions pc-versions-actions">{actions}</div>}</div>
      {versions === null ? <p className="muted">{t("Loading…")}</p> : !versions.length ? <p className="muted">{t("No version saved yet.")}</p>:
        <ol className="pc-version-list">{versions.map((item) => {
          const inner = <>
            <span className="pc-version-head">
              <b className="pc-num">{t("Version {number}", { number: item.number })}</b>
              {item.current && <span className="tag">{t("current")}</span>}
              {item.number === shown && !item.current && <span className="tag tag-old">{t("shown")}</span>}
              {item.name && <span className="pc-version-name">{item.name}</span>}
            </span>
            {item.description && <span className="pc-version-text">{item.description}</span>}
            <small>{[item.author, item.at ? formatDate(item.at) : item.note].filter(Boolean).join(" · ")}</small>
          </>;
          return <li key={item.number} className={item.number === shown ? "active" : undefined}>
            {onOpen
              ? <button type="button" className="pc-version" aria-pressed={item.number === shown} onClick={() => onOpen(item.number)}>{inner}</button>:
              <div className="pc-version">{inner}</div>}
          </li>;
        })}</ol>}
      {footer && <p className="muted small">{footer}</p>}
    </section>
  </div>;
}
