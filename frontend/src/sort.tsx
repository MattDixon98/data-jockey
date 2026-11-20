import { useState } from "react";

export type SortValue = number | string | null | undefined;

/** Per column, the value a row sorts by. */
export type SortKeys<T> = Record<string, (row: T) => SortValue>;

interface Sort {
  key: string;
  descending: boolean;
}

/** Empty values always go last, whichever way the column is sorted. */
function compare(a: SortValue, b: SortValue, descending: boolean): number {
  const aEmpty = a === null || a === undefined;
  const bEmpty = b === null || b === undefined;
  if (aEmpty || bEmpty) return Number(aEmpty) - Number(bEmpty);
  const order = typeof a === "number" && typeof b === "number" ? a - b : String(a).localeCompare(String(b));
  return descending ? -order : order;
}

/**
 * Click-to-sort columns. Clicking a header sorts by it ascending, again
 * descending, a third time back to the rows' own order. Returns the rows in
 * the chosen order and a `header()` that renders a clickable <th>.
 */
export function useSortable<T>(rows: T[], keys: SortKeys<T>) {
  const [sort, setSort] = useState<Sort | null>(null);

  const sorted = sort
    ? [...rows].sort((a, b) => compare(keys[sort.key](a), keys[sort.key](b), sort.descending))
    : rows;

  const toggle = (key: string) =>
    setSort((current) => {
      if (current?.key !== key) return { key, descending: false };
      if (!current.descending) return { key, descending: true };
      return null;
    });

  const header = (key: string, label: string, className?: string) => {
    const active = sort?.key === key;
    const arrow = active ? (sort.descending ? " ▼" : " ▲") : "";
    const ariaSort = active ? (sort.descending ? "descending" : "ascending") : "none";
    return (
      <th className={className} aria-sort={ariaSort}>
        <button type="button" className="sort" onClick={() => toggle(key)}>
          {label}
          {arrow}
        </button>
      </th>
    );
  };

  return { rows: sorted, header };
}
