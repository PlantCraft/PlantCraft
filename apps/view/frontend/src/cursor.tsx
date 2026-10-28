/** The cursor a dashboard's time charts share (Config › Display): hovering one chart marks the same
 * moment on the others, as Grafana's shared crosshair. */
import { createContext, useContext } from "react";

export interface SharedCursor { at: string | null; from: string | null; set: (at: string | null, from: string) => void }

export const CursorContext = createContext<SharedCursor | null>(null);

export function useSharedCursor(): SharedCursor | null {
  return useContext(CursorContext);
}

/** The dotted line a chart draws where another chart is hovered. */
export function cursorShape(at: string, color: string) {
  return { type: "line" as const, xref: "x" as const, yref: "paper" as const, x0: at, x1: at, y0: 0, y1: 1, line: { color, width: 1, dash: "dot" as const } };
}
