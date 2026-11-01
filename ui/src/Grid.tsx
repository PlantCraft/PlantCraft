/**
 * The suite's grid of cards: every Overview's widgets (Desk's first page included) and View's
 * dashboards are placed on it, so a card is moved and resized the same way everywhere (owner,
 * 2026-10-23: "uma coisa para fazer várias"). Twelve columns of 91 px rows with 14 px gaps (the
 * sizes View's dashboards already used); a cell is { i, x, y, w, h } in those units.
 *
 * A row and a gap are those sizes at the default display size. Larger text grows the rows with
 * the text (a card never cuts what it held); smaller sizes keep the rows, so cards show more
 * (`gridRow`, `gridGap`).
 *
 * Dragging and resizing are react-grid-layout's (MIT). On a narrow screen the cells are drawn one
 * under the other, in reading order, and do not move.
 */
import ReactGridLayout, { useContainerWidth, type Layout, type LayoutItem } from "react-grid-layout";
import { useCallback, useState, type ReactNode } from "react";
import { displayScales, type DisplaySize } from "./displaySize.js";
import { useDisplaySize } from "./useDisplaySize.js";

export const GRID_COLUMNS = 12;
export const GRID_ROW = 91;
export const GRID_GAP = 14;
export const GRID_MAX_H = 12;
/**
 * A row's height in pixels at a display size. Larger text grows the rows with the text, so a
 * card holds what it holds at the default. Smaller text keeps the default's rows: the cards stay
 * as tall and show more (more list rows, bigger squares), which is what More space is for.
 */
export function gridRow(size?: DisplaySize): number {
  return Math.round(GRID_ROW * Math.max(1, displayScales(size).text));
}

/** The gap between cards in pixels at a display size: it follows the spacing. */
export function gridGap(size?: DisplaySize): number {
  return Math.round(GRID_GAP * displayScales(size).space);
}

/** Below this width the cells are stacked in one column. */
export const GRID_NARROW = 720;

export type GridCell = { i: string; x: number; y: number; w: number; h: number };
export type GridLimits = { minW?: number; minH?: number; maxH?: number };
/** A card folded to its title on a phone, and how to open or fold it again. */
export type CellFold = { folded: boolean; toggle: () => void };

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, Math.round(Number.isFinite(value) ? value : low)));
}

/** A cell kept inside the grid: whole units, at least one column and row, within twelve columns. */
export function fitCell<T extends GridCell>(cell: T): T {
  const w = clamp(cell.w, 1, GRID_COLUMNS);
  return { ...cell, w, h: clamp(cell.h, 1, GRID_MAX_H), x: clamp(cell.x, 0, GRID_COLUMNS - w), y: clamp(cell.y, 0, 10_000) };
}

/** The first free place for a w x h cell, row by row, left to right, below none of `taken`. */
export function freePlace(taken: GridCell[], w: number, h: number): { x: number; y: number } {
  const width = clamp(w, 1, GRID_COLUMNS);
  const busy = (x: number, y: number) => taken.some((cell) => x < cell.x + cell.w && x + width > cell.x && y < cell.y + cell.h && y + h > cell.y);
  for (let y = 0; y < 10_000; y += 1) {
    for (let x = 0; x + width <= GRID_COLUMNS; x += 1) if (!busy(x, y)) return { x, y };
  }
  return { x: 0, y: bottom(taken) };
}

/** The first row under every cell. */
export function bottom(cells: GridCell[]): number {
  return cells.reduce((low, cell) => Math.max(low, cell.y + cell.h), 0);
}

/** Cells for items in order, each in the first free place (an old ordered list becomes a grid). */
export function packCells(items: Array<{ i: string; w: number; h: number }>, taken: GridCell[] = []): GridCell[] {
  const placed: GridCell[] = [...taken];
  const out: GridCell[] = [];
  for (const item of items) {
    const cell = fitCell({ i: item.i, w: item.w, h: item.h, ...freePlace(placed, item.w, item.h) });
    placed.push(cell);
    out.push(cell);
  }
  return out;
}

/** Reading order: top to bottom, then left to right (the stacked column, the keyboard). */
export function readingOrder<T extends GridCell>(cells: T[]): T[] {
  return [...cells].sort((a, b) => a.y - b.y || a.x - b.x);
}

function sameCells(a: GridCell[], b: GridCell[]): boolean {
  if (a.length !== b.length) return false;
  const byId = new Map(b.map((cell) => [cell.i, cell]));
  return a.every((cell) => {
    const other = byId.get(cell.i);
    return other !== undefined && other.x === cell.x && other.y === cell.y && other.w === cell.w && other.h === cell.h;
  });
}

export type CardGridProps = {
  cells: GridCell[];
  /** Cards move by `handle` (and resize, unless `resizable` is false). */
  editing?: boolean;
  onChange?: (cells: GridCell[]) => void;
  /** Cards may also be resized from their lower right corner (default: while editing). Overview
   * widgets have fixed sizes, chosen in their settings, and only move. */
  resizable?: boolean;
  /** Each card's own size limits. */
  limits?: (id: string) => GridLimits | undefined;
  /** The card for one cell (an element with its own frame); `fold` when it can be folded. */
  render: (id: string, fold?: CellFold) => ReactNode;
  /** On a phone, the cells after this many (in reading order) start folded to their title. */
  foldAfter?: number;
  /** On a phone, each card stacked at its own grid height ("grid", a dashboard's charts), or only
   * as tall as what it shows ("content", Overview widgets: a short list leaves no gap below it). */
  phoneHeight?: "grid" | "content";
  /** The part of a card that drags it (a CSS selector inside the card). */
  handle?: string;
  className?: string;
  label?: string;
};

export function CardGrid({ cells, editing = false, resizable, onChange, limits, render, foldAfter, phoneHeight = "grid", handle = ".pc-cards-handle", className = "", label }: CardGridProps) {
  const { width, containerRef, mounted } = useContainerWidth();
  const size = useDisplaySize();
  const row = gridRow(size);
  const gap = gridGap(size);
  const narrow = mounted && width < GRID_NARROW;
  const [unfolded, setUnfolded] = useState<ReadonlySet<string>>(() => new Set());
  const toggle = useCallback((id: string) => setUnfolded((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  }), []);
  const change = useCallback((layout: Layout) => {
    // Only the person's own moves are kept (the grid also reports its first, packed layout).
    if (!onChange || !editing) return;
    const next = layout.map((item) => fitCell({ i: item.i, x: item.x, y: item.y, w: item.w, h: item.h }));
    if (!sameCells(next, cells)) onChange(next);
  }, [cells, editing, onChange]);
  const layout: LayoutItem[] = cells.map((cell) => {
    const limit = limits?.(cell.i) ?? {};
    return { ...cell, minW: limit.minW ?? 2, minH: limit.minH ?? 1, maxH: limit.maxH ?? GRID_MAX_H, static: !editing, ...(resizable === false ? { isResizable: false } : {}) };
  });
  return <div ref={containerRef} className={`pc-cards${editing ? " pc-cards-editing" : ""} ${className}`.trim()} aria-label={label}>
    {narrow && <div className={`pc-cards-stack${phoneHeight === "content" ? " pc-cards-stack-content" : ""}`}>
      {readingOrder(cells).map((cell, index) => {
        // A phone shows the first cards whole and the rest as titles to open (a long page otherwise).
        const fold: CellFold | undefined = foldAfter !== undefined && !editing && index >= foldAfter ? { folded: !unfolded.has(cell.i), toggle: () => toggle(cell.i) } : undefined;
        return <div key={cell.i} className={`pc-cards-cell${fold?.folded ? " pc-cards-folded" : ""}`} style={fold?.folded || phoneHeight === "content" ? undefined : { minHeight: cell.h * row + (cell.h - 1) * gap }}>{render(cell.i, fold)}</div>;
      })}
    </div>}
    {mounted && !narrow && <ReactGridLayout layout={layout} width={width} onLayoutChange={change}
      gridConfig={{ cols: GRID_COLUMNS, rowHeight: row, margin: [gap, gap], containerPadding: [0, 0] }}
      dragConfig={{ enabled: editing, handle, cancel: "button, a, input, select, textarea, .pc-cards-nodrag" }}
      resizeConfig={{ enabled: editing && resizable !== false, handles: ["se"] }}>
      {cells.map((cell) => <div key={cell.i} className="pc-cards-cell">{render(cell.i)}</div>)}
    </ReactGridLayout>}
  </div>;
}
