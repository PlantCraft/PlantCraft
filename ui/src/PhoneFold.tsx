/**
 * A long page's section, folded to one line on a phone. A loop's page holds a dozen panels
 * (28 000 px on a phone, journey review 2026-10-23); on a phone each secondary part becomes a
 * line to open, on a wider screen it is shown as it is, with no extra frame.
 */
import { ChevronDown } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { GRID_NARROW } from "./Grid.js";

const QUERY = `(max-width: ${GRID_NARROW - 1}px)`;

function narrowNow(): boolean {
  return typeof window !== "undefined" && Boolean(window.matchMedia?.(QUERY).matches);
}

/** Whether the screen is phone-narrow (below the grid's stacking width), following resizes. */
export function useNarrowScreen(): boolean {
  const [narrow, setNarrow] = useState(narrowNow);
  useEffect(() => {
    const media = window.matchMedia?.(QUERY);
    if (!media) return;
    const change = () => setNarrow(media.matches);
    change();
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);
  return narrow;
}

export type PhoneFoldProps = {
  /** The line shown while folded. */
  title: string;
  /** A short hint after the title (a count, a status). */
  hint?: string;
  /** Open from the start on a phone too. */
  open?: boolean;
  children: ReactNode;
};

export function PhoneFold({ title, hint, open = false, children }: PhoneFoldProps) {
  const narrow = useNarrowScreen();
  if (!narrow) return <>{children}</>;
  return <details className="pc-phone-fold" open={open}>
    <summary><span>{title}</span>{hint && <small>{hint}</small>}<ChevronDown size={16} aria-hidden="true" /></summary>
    {children}
  </details>;
}
