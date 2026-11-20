import { Link, useSearchParams } from "react-router-dom";

import { useMeetings, useUndervalued } from "../api";
import { OurOdds, RaceLink, Status, ValueBadge } from "../components";
import { addDays, longDate, ordinal, raceTypeLabel, todayUk } from "../format";
import { type SortKeys, useSortable } from "../sort";
import type { Meeting, Pick } from "../types";

const TOP_PICKS = 10;

/** How far our chance is above the market's, in percentage points. Ranking by
 * the API's `edge` (relative: ours / market's - 1) puts 100/1 outsiders first. */
const gap = (pick: Pick): number => (pick.model_value?.model_prob ?? 0) - (pick.model_value?.market_prob ?? 0);

const PICK_SORT: SortKeys<Pick> = {
  race: (pick) => pick.race.race_time,
  horse: (pick) => pick.horse.name,
  undervalued: (pick) => pick.model_value?.edge,
  market: (pick) => pick.model_value?.market_odds_decimal,
  ours: (pick) => pick.model_odds?.model_odds_decimal,
};

/** The day's most undervalued runners: biggest gap between our chance and the market's first. */
function TopPicks({ date }: { date: string }) {
  const query = useUndervalued(date);
  const top = [...(query.data ?? [])].sort((a, b) => gap(b) - gap(a)).slice(0, TOP_PICKS);
  const { rows: picks, header } = useSortable(top, PICK_SORT);

  return (
    <section className="panel">
      <h2>
        Top undervalued horses <span className="tag">experimental</span>
      </h2>
      <p className="muted small">
        Where our model rates a horse's chance highest above the market's. So far these{" "}
        <Link to="/scorecard">haven't beaten the market</Link>.
      </p>
      <Status query={query}>
        {picks.length ? (
          <table>
            <thead>
              <tr>
                {header("race", "Race")}
                {header("horse", "Horse")}
                {header("undervalued", "Undervalued")}
                {header("market", "Market", "num")}
                {header("ours", "Ours", "num")}
              </tr>
            </thead>
            <tbody>
              {picks.map((pick: Pick) => (
                <tr key={pick.ride_id}>
                  <td>
                    <RaceLink id={pick.race.race_id}>
                      {pick.race.race_time} {pick.race.course?.name}
                    </RaceLink>
                  </td>
                  <td>
                    {pick.horse.name}
                    {pick.finish_position && <div className="muted small">Finished {ordinal(pick.finish_position)}</div>}
                  </td>
                  <td>
                    <ValueBadge runner={pick} />
                  </td>
                  <td className="num">{pick.model_value?.market_odds ?? "–"}</td>
                  <td className="num">
                    <OurOdds runner={pick} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p>No undervalued horses on this day.</p>
        )}
      </Status>
    </section>
  );
}

function MeetingCard({ meeting }: { meeting: Meeting }) {
  return (
    <section className="panel">
      <h2>{meeting.course?.name}</h2>
      <p className="muted">
        {[meeting.going, meeting.surface_summary].filter(Boolean).join(" · ")}
      </p>
      <table>
        <thead>
          <tr>
            <th>Time</th>
            <th>Race</th>
            <th>Our pick</th>
            <th className="num">Runners</th>
          </tr>
        </thead>
        <tbody>
          {meeting.races.map((race) => {
            const top = race.runners.find((runner) => runner.model_odds?.model_rank === 1);
            const winner = race.runners.find((runner) => runner.finish_position === 1);
            return (
              <tr key={race.race_id}>
                <td>{race.race_time}</td>
                <td>
                  <RaceLink id={race.race_id}>{race.name}</RaceLink>
                  <div className="muted small">
                    {[raceTypeLabel(race.race_type), race.distance].filter(Boolean).join(" · ")}
                  </div>
                </td>
                <td>
                  {top ? (
                    <>
                      {top.horse.name} (<OurOdds runner={top} />)
                    </>
                  ) : (
                    <span className="muted">–</span>
                  )}
                  {winner && <div className="muted small">Won: {winner.horse.name}</div>}
                </td>
                <td className="num">{race.runners.length}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

export default function Home() {
  const [params, setParams] = useSearchParams();
  const today = todayUk();
  const date = params.get("date") ?? today;
  const meetings = useMeetings(date);
  const go = (to: string) => setParams(to === today ? {} : { date: to });

  return (
    <>
      <div className="daybar">
        <button onClick={() => go(addDays(date, -1))} aria-label="Previous day">
          ←
        </button>
        <h1>{longDate(date)}</h1>
        <button onClick={() => go(addDays(date, 1))} aria-label="Next day">
          →
        </button>
        {date !== today && <button onClick={() => go(today)}>Today</button>}
      </div>
      <TopPicks date={date} />
      <Status query={meetings}>
        {meetings.data?.length ? (
          meetings.data.map((meeting) => <MeetingCard key={meeting.meeting_id} meeting={meeting} />)
        ) : (
          <p>No UK or Irish racing on this day.</p>
        )}
      </Status>
    </>
  );
}
