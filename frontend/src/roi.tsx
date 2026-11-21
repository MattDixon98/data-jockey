// Top-pick ROI over time: 1 unit per race at SP on our favourite vs the market's,
// from the daily scorecard rows (period_type=day). A plain SVG chart, no chart library.

import { useState } from "react";

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

const WIDTH = 640;
const PLOT_HEIGHT = 220;
const MARGIN = { top: 12, right: 12, left: 52 };
// Every day gets a date label: level while each has this much room, slanted when they'd collide
// (the slanted ones need a taller bottom margin).
const LEVEL_LABEL_WIDTH = 44;
const LEVEL_BOTTOM = 28;
const SLANTED_BOTTOM = 48;

export function RoiChart({ points, cumulative }: { points: RoiPoint[]; cumulative: boolean }) {
  // The hovered day stays set after the pointer leaves, so the cursor and tooltip
  // fade out where they were instead of vanishing.
  const [hovered, setHovered] = useState(Number.MAX_SAFE_INTEGER);
  const [active, setActive] = useState(false);
  const [pointer, setPointer] = useState(0);
  const values = points.flatMap((point) => [point.model, point.market]).filter((v): v is number => v !== null);
  if (!points.length || !values.length) return <p className="muted">No daily results yet.</p>;

  // A fixed -50%..+50% scale, so views and race groups compare at a glance; it only
  // stretches if a value falls outside it (single days often do).
  const yTicks = ticks(Math.min(-0.5, ...values), Math.max(0.5, ...values), 4);
  const yMin = yTicks[0];
  const yMax = yTicks[yTicks.length - 1];
  const times = points.map((point) => Date.parse(`${point.day}T12:00:00Z`));
  const tMin = times[0];
  const tSpan = times[times.length - 1] - tMin || 1;
  const plotWidth = WIDTH - MARGIN.left - MARGIN.right;
  const plotHeight = PLOT_HEIGHT;
  const slanted = points.length > 1 && plotWidth / (points.length - 1) < LEVEL_LABEL_WIDTH;
  const HEIGHT = MARGIN.top + plotHeight + (slanted ? SLANTED_BOTTOM : LEVEL_BOTTOM);
  const axisY = MARGIN.top + plotHeight;
  const x = (i: number) => MARGIN.left + (points.length > 1 ? ((times[i] - tMin) / tSpan) * plotWidth : plotWidth / 2);
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
      <div className="chart-wrap">
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
          {points.map((point, i) => {
            const level = slanted ? null : i === 0 && points.length > 1 ? "start" : i === points.length - 1 && i > 0 ? "end" : "middle";
            return (
              <g key={point.day}>
                <line x1={x(i)} x2={x(i)} y1={axisY} y2={axisY + 4} className="axis" />
                {level ? (
                  <text x={x(i)} y={axisY + 18} textAnchor={level}>
                    {shortDate(point.day)}
                  </text>
                ) : (
                  <text x={x(i)} y={axisY + 10} dy="0.32em" textAnchor="end" transform={`rotate(-45 ${x(i)} ${axisY + 10})`}>
                    {shortDate(point.day)}
                  </text>
                )}
              </g>
            );
          })}
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
