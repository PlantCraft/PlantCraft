/**
 * The suite's table for long lists: sort by any column, search by text, filter a column by its
 * values, pages of 25/50/100, and, when asked, a checkbox per row with actions on the rows ticked
 * ("Remove selected"). Every list that can grow past a screen uses it (owner, 2026-10-21: no
 * table without pages; 2026-10-22: every table pages, filters and sorts the same way).
 */
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Search, X } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { t } from "./i18n.js";
import { MultiSelect } from "./MultiSelect.js";

export type SortValue = string | number | null | undefined;

export type DataColumn<Row> = {
  key: string;
  label: ReactNode;
  /** The cell; left out, the row's field of the same key as text. */
  render?: (row: Row) => ReactNode;
  /** What the column sorts by; left out, the column does not sort. */
  sort?: (row: Row) => SortValue;
  /** Right-aligned numbers. */
  numeric?: boolean;
  className?: string;
  /** A filter above the table (the suite's MultiSelect) that keeps the rows with the values
   * ticked in this column: `true` lists the values found in the rows; `options` fixes the list
   * (e.g. every status, in order). */
  filter?: true | DataFilter<Row>;
};

export type DataFilter<Row> = {
  options?: Array<{ value: string; label: string }>;
  /** The value a row is filtered by; left out, the column's sort value or its field. */
  value?: (row: Row) => string;
  /** The filter's name when the column's label is not text. */
  label?: string;
};

/** The values ticked per column key (none or missing: all). */
export type FilterState = Record<string, string[]>;

export type SortState = { key: string; descending: boolean };

export type DataTableProps<Row> = {
  rows: Row[];
  columns: DataColumn<Row>[];
  rowKey: (row: Row) => string;
  /** The text a row is found by; left out, no search box. */
  searchText?: (row: Row) => string;
  searchPlaceholder?: string;
  /** Sorted this way until the person clicks a header. */
  initialSort?: SortState;
  /** Filters set when the table opens (e.g. {kind: ["backup"]}). */
  initialFilters?: FilterState;
  pageSizes?: number[];
  /** A checkbox per row; `actions` gets the rows ticked. */
  selectable?: boolean;
  actions?: (selected: Row[], clear: () => void) => ReactNode;
  /** Filters or buttons beside the search box. */
  toolbar?: ReactNode;
  empty?: ReactNode;
  onRowClick?: (row: Row) => void;
  /** A class for a row (an alarm's priority band, a disabled entry). */
  rowClassName?: (row: Row) => string | undefined;
  /** Accessible name of the table. */
  label?: string;
  className?: string;
};

const PAGE_SIZES = [25, 50, 100];

function compare(a: SortValue, b: SortValue): number {
  const blankA = a === null || a === undefined || a === "";
  const blankB = b === null || b === undefined || b === "";
  if (blankA || blankB) return blankA === blankB ? 0 : blankA ? 1 : -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

/** The value a row is filtered by in a column. */
export function filterValue<Row>(column: DataColumn<Row>, row: Row): string {
  const spec = typeof column.filter === "object" ? column.filter : undefined;
  if (spec?.value) return spec.value(row);
  const value = column.sort ? column.sort(row) : (row as Record<string, unknown>)[column.key];
  return value === null || value === undefined ? "" : String(value);
}

/** The choices of a column's filter, each with how many rows have it: the fixed list, or the
 * values found in the rows, sorted. */
export function filterOptions<Row>(rows: Row[], column: DataColumn<Row>): Array<{ value: string; label: string; count: number }> {
  const counts = new Map<string, number>();
  for (const row of rows) { const value = filterValue(column, row); if (value) counts.set(value, (counts.get(value) ?? 0) + 1); }
  if (typeof column.filter === "object" && column.filter.options) return column.filter.options.map((item) => ({ ...item, count: counts.get(item.value) ?? 0 }));
  return [...counts.keys()].sort((a, b) => compare(a, b)).map((value) => ({ value, label: value, count: counts.get(value) ?? 0 }));
}

/** The rows as shown: filtered, searched, then sorted (blanks last whichever way), stable. */
export function arrangeRows<Row>(rows: Row[], columns: DataColumn<Row>[], sort: SortState | null, query: string, searchText?: (row: Row) => string, filters?: FilterState): Row[] {
  const active = columns.filter((column) => column.filter && filters?.[column.key]?.length);
  const kept = active.length ? rows.filter((row) => active.every((column) => filters?.[column.key]?.includes(filterValue(column, row)))) : rows;
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const found = words.length && searchText ? kept.filter((row) => { const text = searchText(row).toLowerCase(); return words.every((word) => text.includes(word)); }) : kept;
  const column = sort ? columns.find((item) => item.key === sort.key && item.sort) : undefined;
  if (!column?.sort || !sort) return found;
  const by = column.sort;
  return found.map((row, index) => ({ row, index })).sort((x, y) => {
    const a = by(x.row);
    const b = by(y.row);
    const blank = (value: SortValue) => value === null || value === undefined || value === "";
    if (blank(a) || blank(b)) return compare(a, b) || x.index - y.index;
    return (sort.descending ? -compare(a, b) : compare(a, b)) || x.index - y.index;
  }).map((item) => item.row);
}

/** "26–50 of 132". */
export function pageText(page: number, size: number, total: number): string {
  if (!total) return t("0 of 0");
  const first = page * size + 1;
  return t("{first}–{last} of {total}", { first, last: Math.min(total, first + size - 1), total });
}

export function DataTable<Row>(props: DataTableProps<Row>) {
  const { rows, columns, rowKey, searchText, searchPlaceholder, initialSort, initialFilters, pageSizes = PAGE_SIZES, selectable, actions, toolbar, empty, onRowClick, rowClassName, label, className } = props;
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortState | null>(initialSort ?? null);
  const [size, setSize] = useState(pageSizes[0] ?? 25);
  const [page, setPage] = useState(0);
  const [filters, setFilters] = useState<FilterState>(() => ({ ...initialFilters }));
  const [ticked, setTicked] = useState<Set<string>>(() => new Set());
  const shown = useMemo(() => arrangeRows(rows, columns, sort, query, searchText, filters), [rows, columns, sort, query, searchText, filters]);
  const filterColumns = columns.filter((column) => column.filter);
  const filtering = filterColumns.some((column) => filters[column.key]?.length);
  const pages = Math.max(1, Math.ceil(shown.length / size));
  useEffect(() => { if (page > pages - 1) setPage(pages - 1); }, [page, pages]);
  useEffect(() => setPage(0), [query, size, filters]);
  // Rows that left the list are no longer ticked.
  useEffect(() => {
    setTicked((current) => {
      const keys = new Set(rows.map(rowKey));
      const kept = new Set([...current].filter((key) => keys.has(key)));
      return kept.size === current.size ? current : kept;
    });
  }, [rows, rowKey]);
  const visible = shown.slice(page * size, page * size + size);
  const selected = rows.filter((row) => ticked.has(rowKey(row)));
  const allVisibleTicked = visible.length > 0 && visible.every((row) => ticked.has(rowKey(row)));
  function toggle(key: string) {
    setTicked((current) => { const next = new Set(current); if (next.has(key)) next.delete(key); else next.add(key); return next; });
  }
  function toggleVisible() {
    setTicked((current) => {
      const next = new Set(current);
      for (const row of visible) { if (allVisibleTicked) next.delete(rowKey(row)); else next.add(rowKey(row)); }
      return next;
    });
  }
  function tickAllFound() {
    setTicked(new Set(shown.map(rowKey)));
  }
  function header(column: DataColumn<Row>) {
    if (!column.sort) return column.label;
    const on = sort?.key === column.key;
    const next = () => setSort(on ? (sort?.descending ? null : { key: column.key, descending: true }) : { key: column.key, descending: false });
    return <button type="button" className={`pc-dt-sort${on ? " on" : ""}`} onClick={next}>
      {column.label}
      {on && (sort?.descending ? <ArrowDown size={12} aria-hidden="true" /> : <ArrowUp size={12} aria-hidden="true" />)}
    </button>;
  }
  function filterSelect(column: DataColumn<Row>) {
    const name = (typeof column.filter === "object" && column.filter.label) || (typeof column.label === "string" ? column.label : column.key);
    const options = filterOptions(rows, column).map((item) => ({ id: item.value, label: item.label, count: item.count }));
    return <MultiSelect key={column.key} label={name} options={options} value={filters[column.key] ?? []} onChange={(value) => setFilters({ ...filters, [column.key]: value })} />;
  }
  const showBar = Boolean(searchText || toolbar || filterColumns.length || (selectable && actions));
  return <div className={`pc-dt${className ? ` ${className}` : ""}`}>
    {showBar && <div className="pc-dt-bar">
      {searchText && <label className="pc-dt-search">
        <Search size={15} aria-hidden="true" />
        <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={searchPlaceholder ?? t("Filter")} aria-label={searchPlaceholder ?? t("Filter")} />
      </label>}
      {filterColumns.map(filterSelect)}
      {filtering && <button type="button" className="button button-secondary button-small pc-dt-clear" onClick={() => setFilters({})}><X size={13} aria-hidden="true" /> {t("Clear filters")}</button>}
      {(filtering || query.trim()) && <span className="pc-dt-found">{t("{count} of {total}", { count: shown.length, total: rows.length })}</span>}
      {toolbar}
      {selectable && actions && selected.length > 0 && <div className="pc-dt-selection">
        <span>{t("{count} selected", { count: selected.length })}</span>
        {selected.length < shown.length && <button type="button" className="button button-secondary button-small" onClick={tickAllFound}>{t("Select all {count}", { count: shown.length })}</button>}
        {actions(selected, () => setTicked(new Set()))}
        <button type="button" className="button button-secondary button-small" onClick={() => setTicked(new Set())}>{t("Clear selection")}</button>
      </div>}
    </div>}
    <div className="table-panel pc-dt-scroll">
      <table className="table" aria-label={label}>
        <thead><tr>
          {selectable && <th className="pc-dt-check"><input type="checkbox" checked={allVisibleTicked} onChange={toggleVisible} aria-label={t("Select the rows of this page")} /></th>}
          {columns.map((column) => <th key={column.key} className={[column.numeric ? "num" : "", column.className ?? ""].join(" ").trim() || undefined} aria-sort={sort?.key === column.key ? (sort.descending ? "descending" : "ascending") : undefined}>{header(column)}</th>)}
        </tr></thead>
        <tbody>
          {visible.map((row) => {
            const key = rowKey(row);
            return <tr key={key} className={[onRowClick ? "pc-dt-clickable" : "", rowClassName?.(row) ?? ""].join(" ").trim() || undefined} onClick={onRowClick ? (event) => { if ((event.target as HTMLElement).closest("a,button,input,select,label")) return; onRowClick(row); } : undefined}>
              {selectable && <td className="pc-dt-check"><input type="checkbox" checked={ticked.has(key)} onChange={() => toggle(key)} aria-label={t("Select")} /></td>}
              {columns.map((column) => <td key={column.key} className={[column.numeric ? "num" : "", column.className ?? ""].join(" ").trim() || undefined}>{column.render ? column.render(row) : String((row as Record<string, unknown>)[column.key] ?? "")}</td>)}
            </tr>;
          })}
          {!visible.length && <tr><td colSpan={columns.length + (selectable ? 1 : 0)} className="pc-dt-empty">{query ? t("Nothing matches “{query}”.", { query }) : filtering ? t("Nothing matches the filters.") : empty ?? t("Nothing to show.")}</td></tr>}
        </tbody>
      </table>
    </div>
    {shown.length > pageSizes[0] && <div className="pc-dt-pages">
      <label>{t("Rows per page")}<select value={size} onChange={(event) => setSize(Number(event.target.value))}>{pageSizes.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
      <span className="pc-dt-count">{pageText(page, size, shown.length)}</span>
      <button type="button" className="pcs-icon-button" onClick={() => setPage(page - 1)} disabled={page === 0} aria-label={t("Previous page")}><ChevronLeft size={16} /></button>
      <button type="button" className="pcs-icon-button" onClick={() => setPage(page + 1)} disabled={page >= pages - 1} aria-label={t("Next page")}><ChevronRight size={16} /></button>
    </div>}
  </div>;
}
