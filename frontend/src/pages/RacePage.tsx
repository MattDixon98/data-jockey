import { Link, useParams } from "react-router-dom";

import { useRace } from "../api";
import {
  FavouriteBadge,
  isOurFavourite,
  marketFavourites,
  OurFavouriteBadge,
  OurOdds,
  Status,
  ValueBadge,
} from "../components";
import { longDate, ordinal, percent, raceTypeLabel } from "../format";
import { type SortKeys, useSortable } from "../sort";
import type { Runner } from "../types";

const RUNNER_SORT: SortKeys<Runner> = {
  position: (runner) => runner.finish_position,
  cloth: (runner) => runner.cloth_number,
  horse: (runner) => runner.horse.name,
  jockey: (runner) => runner.jockey?.name,
  odds: (runner) => runner.odds_decimal,
  ours: (runner) => runner.model_odds?.model_odds_decimal,
  chance: (runner) => runner.model_odds?.model_prob,
};

export default function RacePage() {
  const { raceId = "" } = useParams();
  const query = useRace(raceId);
  const race = query.data;
  const done = race?.result_status === "complete";
  const { rows: runners, header } = useSortable(race?.runners ?? [], RUNNER_SORT);
  const favourites = marketFavourites(race?.runners ?? []);

  return (
    <Status query={query}>
      {race && (
        <>
          <p>
            <Link to={`/?date=${race.race_date}`}>← {longDate(race.race_date)}</Link>
          </p>
          <h1>
            {race.race_time} {race.course?.name}
          </h1>
          <h2>{race.name}</h2>
          <p className="muted">
            {[
              raceTypeLabel(race.race_type),
              race.race_class ? `Class ${race.race_class}` : null,
              race.age_band,
              race.distance,
              race.going,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
          {race.verdict && <p className="verdict">{race.verdict}</p>}
          <section className="panel">
            <table>
              <thead>
                <tr>
                  {done && header("position", "Pos")}
                  {header("cloth", "No.", "num")}
                  {header("horse", "Horse")}
                  {header("jockey", "Jockey / trainer")}
                  {header("odds", done ? "SP" : "Odds", "num")}
                  {header("ours", "Ours", "num")}
                  {header("chance", "Our chance", "num")}
                </tr>
              </thead>
              <tbody>
                {runners.map((runner) => (
                  <tr key={runner.ride_id} className={runner.status === "RUNNER" ? "" : "gone"}>
                    {done && <td>{runner.finish_position ? ordinal(runner.finish_position) : runner.non_finisher_reason ?? "–"}</td>}
                    <td className="num">{runner.cloth_number}</td>
                    <td>
                      {runner.horse.name}
                      {runner.status !== "RUNNER" && <span className="tag">non-runner</span>}{" "}
                      {favourites.has(runner.ride_id) && <FavouriteBadge />}{" "}
                      {isOurFavourite(runner) && <OurFavouriteBadge />} <ValueBadge runner={runner} />
                      <div className="muted small">
                        {[runner.horse_age ? `${runner.horse_age}yo` : null, runner.weight, runner.official_rating ? `OR ${runner.official_rating}` : null]
                          .filter(Boolean)
                          .join(" · ")}
                      </div>
                    </td>
                    <td>
                      {runner.jockey?.name}
                      <div className="muted small">{runner.trainer?.name}</div>
                    </td>
                    <td className="num">{runner.odds ?? "–"}</td>
                    <td className="num">
                      <OurOdds runner={runner} />
                    </td>
                    <td className="num">{percent(runner.model_odds?.model_prob ?? null, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
          {race.betting_forecast && <p className="muted">Forecast: {race.betting_forecast}</p>}
        </>
      )}
    </Status>
  );
}
