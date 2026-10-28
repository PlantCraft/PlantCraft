/** The viewer's zoom (owner, 2026-10-27: a whole plant on one page, looked at closely): which part
 * of the canvas is shown, kept inside it, from the whole canvas down to an eighth of it. */
import type { ViewBox } from "./DiagramCanvas";

export const MAX_ZOOM = 8;

/** The whole canvas. */
export function fullView(width: number, height: number): ViewBox {
  return { x: 0, y: 0, w: width, h: height };
}

/** `view` kept inside the canvas, at most the whole of it and at least an eighth. */
export function clampView(view: ViewBox, width: number, height: number): ViewBox {
  const w = Math.min(width, Math.max(width / MAX_ZOOM, view.w));
  const h = (w / width) * height;
  return { x: Math.min(width - w, Math.max(0, view.x)), y: Math.min(height - h, Math.max(0, view.y)), w, h };
}

/** `factor` times closer (below 1: farther), the point (`px`, `py`) of the canvas staying where
 * it is on the screen. */
export function zoomAt(view: ViewBox, factor: number, px: number, py: number, width: number, height: number): ViewBox {
  const w = Math.min(width, Math.max(width / MAX_ZOOM, view.w / factor));
  const ratio = w / view.w;
  return clampView({ x: px - (px - view.x) * ratio, y: py - (py - view.y) * ratio, w, h: view.h * ratio }, width, height);
}

/** How much closer than the whole canvas, for the zoom's label. */
export function zoomLevel(view: ViewBox, width: number): number {
  return width / view.w;
}
