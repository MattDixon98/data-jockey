import { useScorecard } from "../api";
import { Status } from "../components";
import { percent, signedPercent } from "../format";

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
    </>
  );
}
