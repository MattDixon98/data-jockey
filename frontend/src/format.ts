/** Today's date in UK time, YYYY-MM-DD (races are dated in UK time). */
export function todayUk(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/London" }).format(new Date());
}

export function addDays(date: string, days: number): string {
  const moved = new Date(`${date}T12:00:00Z`);
  moved.setUTCDate(moved.getUTCDate() + days);
  return moved.toISOString().slice(0, 10);
}

export function longDate(date: string): string {
  return new Date(`${date}T12:00:00Z`).toLocaleDateString("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

export const percent = (value: number | null, digits = 0): string =>
  value === null ? "–" : `${(value * 100).toFixed(digits)}%`;

export const signedPercent = (value: number | null, digits = 0): string =>
  value === null ? "–" : `${value > 0 ? "+" : ""}${(value * 100).toFixed(digits)}%`;

export function ordinal(position: number): string {
  const teens = position % 100 >= 11 && position % 100 <= 13;
  const suffix = teens ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[position % 10] ?? "th";
  return `${position}${suffix}`;
}

export const raceTypeLabel = (type: string | null): string =>
  type ? type.charAt(0) + type.slice(1).toLowerCase().replace(/_/g, " ") : "";
