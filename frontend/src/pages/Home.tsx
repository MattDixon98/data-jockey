import { Link, useSearchParams } from "react-router-dom";

import { useMeetings, useUndervalued } from "../api";
import { OurOdds, RaceLink, Status, ValueBadge } from "../components";
import { addDays, longDate, raceTypeLabel, todayUk } from "../format";
import type { Meeting, Pick } from "../types";

function Picks({ date }: { date: string }) {
  const picks = useUndervalued(date);
  return (
    <section className="panel">
      <h2>
        Undervalued runners <span className="tag">experimental</span>
      </h2>
      <p className="muted">
        Where our model gives a horse a better chance than the betting market does.{" "}
        <Link to="/scorecard">So far it hasn't beaten the market</Link>, so treat these as a curiosity.
      </p>
      <Status query={picks}>
        {picks.data?.length ? (
          <table>
            <thead>
              <tr>
                <th>Race</th>
                <th>Horse</th>
                <th className="num">Market</th>
                <th className="num">Ours</th>
              </tr>
            </thead>
            <tbody>
              {picks.data.map((pick: Pick) => (
                <tr key={pick.ride_id}>
                  <td>
                    <RaceLink id={pick.race.race_id}>
                      {pick.race.race_time} {pick.race.course?.name}
                    </RaceLink>
                  </td>
                  <td>
                    {pick.horse.name} <ValueBadge runner={pick} />
                  </td>
                  <td className="num">{pick.model_value?.market_odds ?? pick.odds ?? "–"}</td>
                  <td className="num">
                    <OurOdds runner={pick} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p>No undervalued runners for this day.</p>
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
      <Picks date={date} />
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
