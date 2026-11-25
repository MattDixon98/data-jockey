// Top-pick ROI over time: 1 unit per race at SP on our favourite vs the market's,
// from the daily scorecard rows (period_type=day). A plain SVG chart, no chart library.

import { useCallback, useState } from "react";

import { signedPercent } from "./format";
import type { ScorecardRow } from "./types";

export interface RoiPoint {
  day: string;
  races: number;
  model: number | null;
  market: number | null;
}

type Line = "model" | "market";

// Ours in the site's accent green, the market as the muted, dashed benchmark.
export const LINES: { key: Line; label: string; className: string }[] = [
  { key: "model", label: "Our favourite", className: "ours" },
  { key: "market", label: "Market favourite", className: "market" },
];

/**
 * One point per race day, ROI per unit staked. Cumulative = total profit so far /
 * races so far (each strategy stakes 1 unit per race); a day without a profit for
 * a line doesn't count towards that line.
 */
export function roiByDay(rows: ScorecardRow[], cumulative: boolean): RoiPoint[] {
  const days = [...rows].sort((a, b) => a.period.localeCompare(b.period));
  if (!cumulative) {
    return days.map((row) => ({
      day: row.period,
      races: row.races,
      model: row.top_pick_roi_model,
      market: row.top_pick_roi_market,
    }));
  }
  const totals = { model: { profit: 0, races: 0 }, market: { profit: 0, races: 0 } };
  const running = (line: Line, profit: number | null, races: number): number | null => {
    const total = totals[line];
    if (profit !== null) {
      total.profit += profit;
      total.races += races;
    }
    return total.races ? total.profit / total.races : null;
  };
  return days.map((row) => ({
    day: row.period,
    races: row.races,
    model: running("model", row.top_pick_profit_model, row.races),
    market: running("market", row.top_pick_profit_market, row.races),
  }));
}

/**
 * The last 12 months of points (days after the same date a year before the last day):
 * the chart is a rolling year once there's more than that. Cumulative values keep
 * counting from the first day, only the display is cut.
 */
export function lastYear(points: RoiPoint[]): RoiPoint[] {
  if (!points.length) return points;
  const start = new Date(`${points[points.length - 1].day}T12:00:00Z`);
  start.setUTCFullYear(start.getUTCFullYear() - 1);
  const from = start.toISOString().slice(0, 10);
  return points.filter((point) => point.day > from);
}

/** Round tick values (1, 2, 2.5 or 5 × 10^n apart) covering min..max, about `count` of them. */
function ticks(min: number, max: number, count = 5): number[] {
  const rough = (max - min) / count || 0.01;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= rough) ?? rough;
  const values = [];
  for (let value = Math.floor(min / step) * step; value <= max + step / 2; value += step) {
    values.push(Number(value.toFixed(10)));
  }
  return values;
}

const shortDate = (day: string): string =>
  new Date(`${day}T12:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

const DAY = 86_400_000;
// Before the chart has been measured, and the room each x-axis label needs (13px text:
// "24 Nov" or "Sept 2027", plus a gap). The chart draws at its real width, so text stays
// 13px on any screen and narrow screens just get fewer labels.
const FALLBACK_WIDTH = 640;
const MIN_LABEL_GAP = 64;
const MAX_LABELS = 12;
const MARGIN = { top: 12, right: 36, bottom: 28, left: 52 };

/** The width an element is drawn at, kept up to date as it resizes. */
function useWidth(): [(node: HTMLElement | null) => (() => void) | undefined, number] {
  const [width, setWidth] = useState(0);
  const ref = useCallback((node: HTMLElement | null) => {
    if (!node) return undefined;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

interface Tick {
  time: number;
  label: string;
}

// Calendar steps for the x-axis, finest first: every n days from the first day, then
// the 1st of every n months (Jan-aligned, so 3 months = quarters).
const DAY_STEPS = [1, 2, 3, 7, 14];
const MONTH_STEPS = [1, 2, 3, 6, 12];

// "Dec", with the year on January and on the ends ("Nov 2026"), so every year is named.
const monthLabel = (time: number, withYear = false): string =>
  new Date(time).toLocaleDateString("en-GB", {
    month: "short",
    year: withYear || new Date(time).getUTCMonth() === 0 ? "numeric" : undefined,
    timeZone: "UTC",
  });

const monthOf = (time: number): number => new Date(time).getUTCFullYear() * 12 + new Date(time).getUTCMonth();

/** Ticks strictly between tMin and tMax (both at 12:00 UTC) for one calendar step. */
function innerTicks(tMin: number, tMax: number, step: { days: number } | { months: number }): Tick[] {
  const ticks: Tick[] = [];
  if ("days" in step) {
    for (let time = tMin + step.days * DAY; time < tMax; time += step.days * DAY) {
      ticks.push({ time, label: shortDate(new Date(time).toISOString().slice(0, 10)) });
    }
    return ticks;
  }
  const start = new Date(tMin);
  for (let month = start.getUTCFullYear() * 12 + start.getUTCMonth() + 1; ; month++) {
    const time = Date.UTC(Math.floor(month / 12), month % 12, 1, 12);
    if (time >= tMax) break;
    if (month % step.months === 0) ticks.push({ time, label: monthLabel(time) });
  }
  return ticks;
}

/**
 * The x-axis labels: always the first and last day, plus the finest calendar step whose
 * labels have room and that keeps the total within `maxLabels`. A step tick too close to
 * either end to fit a label is dropped, so the ends can sit a little closer to their
 * neighbours than the rest. On a month step the ends are months too ("Nov 2026"), and a
 * step tick in the same month as an end is dropped rather than repeat it.
 */
function xTicks(tMin: number, tMax: number, maxLabels: number, x: (time: number) => number): Tick[] {
  const first = { time: tMin, label: shortDate(new Date(tMin).toISOString().slice(0, 10)) };
  if (tMax === tMin) return [first];
  const last = { time: tMax, label: shortDate(new Date(tMax).toISOString().slice(0, 10)) };
  const steps = [...DAY_STEPS.map((days) => ({ days })), ...MONTH_STEPS.map((months) => ({ months }))];
  for (const step of steps) {
    // Months are 28-31 days: 30 is close enough to tell whether their labels fit.
    const stepDays = "days" in step ? step.days : step.months * 30;
    if (x(tMin + stepDays * DAY) - x(tMin) < MIN_LABEL_GAP) continue;
    const months = "months" in step;
    const roomy = (tick: Tick) => x(tick.time) - x(tMin) >= MIN_LABEL_GAP && x(tMax) - x(tick.time) >= MIN_LABEL_GAP;
    const ownMonth = (tick: Tick) => !months || (monthOf(tick.time) !== monthOf(tMin) && monthOf(tick.time) !== monthOf(tMax));
    const inner = innerTicks(tMin, tMax, step).filter((tick) => roomy(tick) && ownMonth(tick));
    if (inner.length + 2 > maxLabels) continue;
    if (!months) return [first, ...inner, last];
    return [{ time: tMin, label: monthLabel(tMin, true) }, ...inner, { time: tMax, label: monthLabel(tMax, true) }];
  }
  return [first, last];
}

export function RoiChart({ points, cumulative }: { points: RoiPoint[]; cumulative: boolean }) {
  // The hovered day stays set after the pointer leaves, so the cursor and tooltip
  // fade out where they were instead of vanishing.
  const [hovered, setHovered] = useState(Number.MAX_SAFE_INTEGER);
  const [active, setActive] = useState(false);
  const [pointer, setPointer] = useState(0);
  const [wrapRef, measured] = useWidth();
  const values = points.flatMap((point) => [point.model, point.market]).filter((v): v is number => v !== null);
  if (!points.length || !values.length) return <p className="muted">No daily results yet.</p>;

  // A fixed -50%..+50% scale, so views and race groups compare at a glance; it only
  // stretches if a value falls outside it (single days often do).
  const yTicks = ticks(Math.min(-0.5, ...values), Math.max(0.5, ...values), 4);
  const yMin = yTicks[0];
  const yMax = yTicks[yTicks.length - 1];
  const times = points.map((point) => Date.parse(`${point.day}T12:00:00Z`));
  const tMin = times[0];
  const tMax = times[times.length - 1];
  const tSpan = tMax - tMin || 1;
  const WIDTH = measured || FALLBACK_WIDTH;
  const plotWidth = WIDTH - MARGIN.left - MARGIN.right;
  // Shorter on phones, so the lines don't flatten out on a wide screen or tower on a narrow one.
  const plotHeight = Math.round(Math.min(280, Math.max(180, WIDTH * 0.32)));
  const HEIGHT = MARGIN.top + plotHeight + MARGIN.bottom;
  const axisY = MARGIN.top + plotHeight;
  const xAt = (time: number) => MARGIN.left + (tMax > tMin ? ((time - tMin) / tSpan) * plotWidth : plotWidth / 2);
  const x = (i: number) => xAt(times[i]);
  const maxLabels = Math.min(MAX_LABELS, Math.floor(plotWidth / MIN_LABEL_GAP) + 1);
  const labels = xTicks(tMin, tMax, maxLabels, xAt);
  const y = (value: number) => MARGIN.top + ((yMax - value) / (yMax - yMin || 1)) * plotHeight;

  const path = (line: Line) =>
    points
      .map((point, i) => (point[line] === null ? null : `${x(i).toFixed(1)},${y(point[line]!).toFixed(1)}`))
      .filter(Boolean)
      .join(" ");

  // The nearest day to the pointer, in the SVG's own coordinates; the tooltip
  // follows the pointer itself.
  const onPointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const fraction = Math.min(1, Math.max(0, (event.clientX - box.left) / box.width));
    const pointerX = fraction * WIDTH;
    let nearest = 0;
    points.forEach((_, i) => {
      if (Math.abs(x(i) - pointerX) < Math.abs(x(nearest) - pointerX)) nearest = i;
    });
    setHovered(nearest);
    setPointer(fraction);
    setActive(true);
  };

  const latest = points[points.length - 1];
  const index = Math.min(hovered, points.length - 1);
  const shown = points[index];
  const showDots = active || points.length === 1;
  // The tooltip sits beside the pointer, on whichever side has more room.
  const flip = pointer > 0.6;
  // Changes when the data does (another view, race group or mode), so the lines fade in again.
  const dataKey = points.map((point) => `${point.day}:${point.model}:${point.market}`).join("|");
  const on = (className: string, visible: boolean) => (visible ? `${className} on` : className);

  return (
    <>
      <div className="legend">
        <span className="muted">{cumulative ? "To date" : `Last day, ${shortDate(latest.day)}`}</span>
        {LINES.map((line) => (
          <span key={line.key}>
            <span className={`swatch ${line.className}`} />
            {line.label} <strong>{signedPercent(latest[line.key], 1)}</strong>
          </span>
        ))}
      </div>
      <div className="chart-wrap" ref={wrapRef}>
        <svg
          className="chart"
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          role="img"
          aria-label="Return on investment by race day, our favourite vs the market favourite"
          onPointerMove={onPointerMove}
          onPointerLeave={() => setActive(false)}
        >
          {yTicks.map((tick) => (
            <g key={tick}>
              <line
                x1={MARGIN.left}
                x2={WIDTH - MARGIN.right}
                y1={y(tick)}
                y2={y(tick)}
                className={tick === 0 ? "axis zero" : "axis"}
              />
              <text x={MARGIN.left - 8} y={y(tick)} dy="0.32em" textAnchor="end">
                {signedPercent(tick)}
              </text>
            </g>
          ))}
          {labels.map((tick) => (
            <g key={tick.time}>
              <line x1={xAt(tick.time)} x2={xAt(tick.time)} y1={axisY} y2={axisY + 4} className="axis" />
              <text x={xAt(tick.time)} y={axisY + 18} textAnchor="middle">
                {tick.label}
              </text>
            </g>
          ))}
          <line
            y1={MARGIN.top}
            y2={MARGIN.top + plotHeight}
            className={on("cursor", active)}
            style={{ transform: `translateX(${x(index)}px)` }}
          />
          <g key={dataKey} className="lines">
            {LINES.map((line) => (
              <g key={line.key} className={`series ${line.className}`}>
                <polyline points={path(line.key)} />
              </g>
            ))}
          </g>
          {LINES.map((line) => {
            const value = shown[line.key];
            if (value === null) return null;
            return (
              <g key={line.key} className={`series ${line.className}`}>
                <circle
                  r={4.5}
                  className={on("dot", showDots)}
                  style={{ transform: `translate(${x(index)}px, ${y(value)}px)` }}
                />
              </g>
            );
          })}
        </svg>
        <div
          className={on("tooltip", active)}
          aria-hidden={!active}
          style={{
            left: `${pointer * 100}%`,
            transform: flip ? "translateX(calc(-100% - 16px))" : "translateX(16px)",
          }}
        >
          <div className="tooltip-head">
            {shortDate(shown.day)} · {shown.races} races
          </div>
          {LINES.map((line) => (
            <div key={line.key} className="tooltip-row">
              <span>
                <span className={`swatch ${line.className}`} />
                {line.label}
              </span>
              <strong>{signedPercent(shown[line.key], 1)}</strong>
            </div>
          ))}
          {cumulative && <div className="muted small">All time, up to this day</div>}
        </div>
      </div>
    </>
  );
}
