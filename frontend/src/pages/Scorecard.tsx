import { useState } from "react";

import { useDailyScorecard, useScorecard } from "../api";
import { Status } from "../components";
import { percent, signedPercent } from "../format";
import { RoiChart, lastYear, roiByDay } from "../roi";

export default function Scorecard() {
  const query = useScorecard();
  const rows = (query.data ?? []).filter(
    (row) => row.period_type === "all" && row.view === "after_race" && row.race_group === "all",
  );
  const row = rows[0];

  return (
    <>
      <h1>Track record</h1>
      <p className="muted">
        How our win odds have done on races they weren't trained on, judged against the starting price. Lower
        log-loss is better; the market is the bar to beat.
      </p>
      <Status query={query}>
        {row ? (
          <section className="panel">
            <p>
              {row.races} races, {row.first_race} to {row.last_race}
            </p>
            <table>
              <thead>
                <tr>
                  <th />
                  <th className="num">Our model</th>
                  <th className="num">Market (SP)</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Log-loss (lower is better)</td>
                  <td className="num">{row.log_loss_model?.toFixed(3)}</td>
                  <td className="num">{row.log_loss_market?.toFixed(3)}</td>
                </tr>
                <tr>
                  <td>Favourite / top pick won</td>
                  <td className="num">{percent(row.top_pick_won_model)}</td>
                  <td className="num">{percent(row.top_pick_won_market)}</td>
                </tr>
                <tr>
                  <td>Return backing the favourite / top pick at SP</td>
                  <td className="num">{signedPercent(row.top_pick_roi_model)}</td>
                  <td className="num">{signedPercent(row.top_pick_roi_market)}</td>
                </tr>
              </tbody>
            </table>
            <p>
              Betting every undervalued runner at SP: {row.bets_won} winners from {row.bets} bets, return on
              investment {signedPercent(row.roi)}.
            </p>
          </section>
        ) : (
          <p>No results yet.</p>
        )}
      </Status>
      <TopPickRoi />
    </>
  );
}

const VIEWS = [
  { key: "after_race", label: "After the race", hint: "market = SP" },
  { key: "site_pick", label: "Race morning", hint: "market = forecast" },
];

function Choice<T extends string>({ options, value, onChange }: {
  options: { key: T; label: string; title?: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="choice">
      {options.map((option) => (
        <button
          key={option.key}
          className={option.key === value ? "active" : undefined}
          aria-pressed={option.key === value}
          title={option.title}
          onClick={() => onChange(option.key)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** Top-pick ROI by race day, ours vs the market's favourite. */
function TopPickRoi() {
  const [view, setView] = useState("after_race");
  const [group, setGroup] = useState("all");
  const [cumulative, setCumulative] = useState(false);
  const query = useDailyScorecard(view);
  const rows = query.data ?? [];
  const groups = [...new Set(rows.map((row) => row.race_group))].sort(
    (a, b) => Number(a !== "all") - Number(b !== "all") || a.localeCompare(b),
  );
  const dayRows = rows.filter((row) => row.race_group === group);
  const allPoints = roiByDay(dayRows, cumulative);
  const points = lastYear(allPoints);
  const races = points.reduce((total, point) => total + point.races, 0);

  return (
    <section className="panel">
      <h2>Backing the favourite, day by day</h2>
      <p className="muted small">
        1 unit per race at SP on our favourite vs the market's favourite, out-of-sample races only. Joint
        favourites split the unit.
      </p>
      <div className="controls">
        <Choice
          options={VIEWS.map((v) => ({ key: v.key, label: v.label, title: v.hint }))}
          value={view}
          onChange={setView}
        />
        {groups.length > 1 && (
          <Choice
            options={groups.map((g) => ({ key: g, label: g.charAt(0).toUpperCase() + g.slice(1) }))}
            value={group}
            onChange={setGroup}
          />
        )}
        <Choice
          options={[
            { key: "total", label: "All time", title: "Everything up to each day: profit so far / races so far" },
            { key: "daily", label: "Daily", title: "Each day on its own: a few races, so noisy" },
          ]}
          value={cumulative ? "total" : "daily"}
          onChange={(choice) => setCumulative(choice === "total")}
        />
      </div>
      <Status query={query}>
        <RoiChart points={points} cumulative={cumulative} />
        {points.length > 0 && (
          <p className="muted small">
            {races} races over {points.length} race days
            {points.length < allPoints.length ? ", the last 12 months" : ""}.
          </p>
        )}
      </Status>
    </section>
  );
}
